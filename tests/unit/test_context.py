"""Unit tests for the context module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.context import ContextRuntimeError, PluginContext


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
