"""Unit tests for the context module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.context import ContextRuntimeError, PluginContext
from modules.general import exec_dialog
from modules.print_layout_export import LayoutSelectionDialog, _archive_existing_pdf


class TestPluginContext:
    """Tests for the PluginContext singleton-like class."""

    def test_init_and_accessors(self) -> None:
        """Test basic initialization and simple accessors."""
        iface = MagicMock()
        plugin_dir = Path("/mock/plugin/dir")

        PluginContext.init(iface, plugin_dir)

        assert PluginContext.iface() == iface
        assert PluginContext.plugin_dir() == plugin_dir
        assert PluginContext.resources_path() == plugin_dir / "resources"
        assert PluginContext.icons_path() == plugin_dir / "resources" / "icons"

    def test_uninitialized_error(self) -> None:
        """Test error when accessing uninitialized context."""
        PluginContext._iface = None
        PluginContext._plugin_dir = None

        with pytest.raises(ContextRuntimeError, match="not initialized with iface"):
            PluginContext.iface()

        with pytest.raises(
            ContextRuntimeError, match="not initialized with plugin_dir"
        ):
            PluginContext.plugin_dir()

    @patch("qgis.core.QgsProject.instance")
    def test_project_path(self, mock_project_instance: MagicMock) -> None:
        """Test project path and gpkg derivation."""
        project = MagicMock()
        project.fileName.return_value = "/data/my_project.qgz"
        mock_project_instance.return_value = project

        # Ensure context is initialized for iface if needed (though not by this method)

        assert PluginContext.project_path() == Path("/data/my_project.qgz")
        assert PluginContext.project_gpkg() == Path("/data/my_project.gpkg")

    @patch("qgis.core.QgsProject.instance")
    def test_project_not_saved_error(self, mock_project_instance: MagicMock) -> None:
        """Test error when project is not saved."""
        project = MagicMock()
        project.fileName.return_value = ""
        mock_project_instance.return_value = project

        with pytest.raises(ContextRuntimeError, match="Project is not saved"):
            PluginContext.project_path()

    def test_version_checks(self) -> None:
        """Test QGIS and Qt version check methods."""
        # These depend on constants but we can verify logic
        # QGIS 3.28.0 = 32800 -> is_qgis4 False
        with patch("qgis.core.Qgis.QGIS_VERSION_INT", 32800):
            assert PluginContext.is_qgis4() is False

        # QGIS 4.0.0 = 40000 -> is_qgis4 True
        with patch("qgis.core.Qgis.QGIS_VERSION_INT", 40000):
            assert PluginContext.is_qgis4() is True

    @patch("modules.context.QT_VERSION_STR", "6.5.0")
    def test_is_qt6_true(self) -> None:
        """Test is_qt6 when running on Qt 6."""
        assert PluginContext.is_qt6() is True

    @patch("modules.context.QT_VERSION_STR", "5.15.2")
    def test_is_qt6_false(self) -> None:
        """Test is_qt6 when running on Qt 5."""
        assert PluginContext.is_qt6() is False

    def test_is_dark_theme(self) -> None:
        """Test dark theme detection logic."""
        iface = MagicMock()
        window = MagicMock()
        iface.mainWindow.return_value = window

        # Mock color luminance
        color = MagicMock()
        window.palette().color.return_value = color

        PluginContext.init(iface, Path())

        # Dark theme (value < 128)
        color.value.return_value = 100
        assert PluginContext.is_dark_theme() is True

        # Light theme (value >= 128)
        color.value.return_value = 200
        assert PluginContext.is_dark_theme() is False


class TestExecDialog:
    """Tests for Qt-version-specific modal dialog execution."""

    @patch("modules.general.PluginContext.is_qt6", return_value=True)
    def test_uses_qt6_exec(self, _is_qt6: MagicMock) -> None:
        dialog = MagicMock()
        dialog.exec.return_value = 1

        assert exec_dialog(dialog) == 1
        dialog.exec.assert_called_once()
        dialog.exec_.assert_not_called()

    @patch("modules.general.PluginContext.is_qt6", return_value=False)
    def test_uses_qt5_exec_underscore(self, _is_qt6: MagicMock) -> None:
        dialog = MagicMock()
        dialog.exec_.return_value = 1

        assert exec_dialog(dialog) == 1
        dialog.exec_.assert_called_once()
        dialog.exec.assert_not_called()


class TestArchiveExistingPdf:
    """Tests for preserving existing PDFs before export."""

    def test_archives_existing_file(self, tmp_path: Path) -> None:
        pdf_path = tmp_path / "layout.pdf"
        pdf_path.write_text("existing", encoding="utf-8")

        assert _archive_existing_pdf(pdf_path)
        assert not pdf_path.exists()
        assert (tmp_path / "alt" / "layout.pdf").read_text(encoding="utf-8") == (
            "existing"
        )

    def test_reports_archive_failure_without_removing_original(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        pdf_path = tmp_path / "layout.pdf"
        pdf_path.write_text("existing", encoding="utf-8")

        def fail_rename(_path: Path, _target: Path) -> Path:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "rename", fail_rename)

        assert not _archive_existing_pdf(pdf_path)
        assert pdf_path.read_text(encoding="utf-8") == "existing"


class TestLayoutSelectionDialog:
    """Tests for the layout export dialog filename settings."""

    @patch("modules.print_layout_export.PluginContext.project_path")
    @patch("modules.print_layout_export.PluginContext.iface")
    def test_default_prefix_and_preview(
        self,
        mock_iface: MagicMock,
        mock_project_path: MagicMock,
    ) -> None:
        """The prefix should default to the project name with a trailing separator."""
        mock_project_path.return_value = Path("/data/example_project.qgz")
        mock_iface.return_value.mainWindow.return_value = None

        layout_a = MagicMock()
        layout_a.name.return_value = "First Layout"
        layout_b = MagicMock()
        layout_b.name.return_value = "Second Layout"

        dialog = LayoutSelectionDialog([layout_a, layout_b])

        assert dialog.prefix_edit.text() == "example_project - "
        assert dialog.prefix_preview.text() == "example_project - First Layout.pdf"

    @patch("modules.print_layout_export.PluginContext.project_path")
    @patch("modules.print_layout_export.PluginContext.iface")
    def test_custom_prefix_uses_selected_layout_name(
        self,
        mock_iface: MagicMock,
        mock_project_path: MagicMock,
    ) -> None:
        """A custom prefix should be applied to the exported file name."""
        mock_project_path.return_value = Path("/data/example_project.qgz")
        mock_iface.return_value.mainWindow.return_value = None

        layout_a = MagicMock()
        layout_a.name.return_value = "First Layout"
        layout_b = MagicMock()
        layout_b.name.return_value = "Second Layout"

        dialog = LayoutSelectionDialog([layout_a, layout_b])
        dialog.prefix_edit.setText("Custom prefix - ")

        assert (
            dialog.get_export_filename("Second Layout")
            == "Custom prefix - Second Layout.pdf"
        )
