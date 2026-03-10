"""Unit tests for the shipping module (internal functions)."""

from unittest.mock import MagicMock, patch

from qgis.core import QgsPrintLayout, QgsRectangle

from modules.shipping import _copy_layouts, _copy_project_properties, _set_map_extent


class TestShippingInternals:
    """Tests for private helper functions in shipping.py."""

    def test_copy_layouts(self) -> None:
        """Test copying layouts from source to target project."""
        source_project = MagicMock()
        target_project = MagicMock()

        source_manager = MagicMock()
        target_manager = MagicMock()

        source_project.layoutManager.return_value = source_manager
        target_project.layoutManager.return_value = target_manager

        layout1 = MagicMock(spec=QgsPrintLayout)
        layout2 = MagicMock()  # Not a print layout

        source_manager.layouts.return_value = [layout1, layout2]
        target_manager.layouts.return_value = [
            MagicMock()
        ]  # Existing layout to be removed

        cloned_layout = MagicMock(spec=QgsPrintLayout)
        layout1.clone.return_value = cloned_layout

        _copy_layouts(source_project, target_project)

        # Verify removal of existing layouts
        target_manager.removeLayout.assert_called_once()

        # Verify cloning and adding of print layouts
        layout1.clone.assert_called_once()
        target_manager.addLayout.assert_called_with(cloned_layout)

    def test_copy_project_properties(self) -> None:
        """Test copying CRS, Title, and Map Themes."""
        source_project = MagicMock()
        target_project = MagicMock()

        crs = MagicMock()
        title = "Test Project Title"

        source_project.crs.return_value = crs
        source_project.title.return_value = title
        source_project.mapThemeCollection.return_value = (
            None  # Simplify XML test for now
        )

        # _copy_layouts is called inside
        with patch("modules.shipping._copy_layouts") as mock_copy_layouts:
            _copy_project_properties(source_project, target_project)

            target_project.setCrs.assert_called_with(crs)
            target_project.setTitle.assert_called_with(title)
            mock_copy_layouts.assert_called_once_with(source_project, target_project)

    @patch("modules.shipping.QgsReferencedRectangle")
    def test_set_map_extent(self, mock_ref_rect: MagicMock) -> None:
        """Test setting map extent from canvas to project view settings."""
        canvas = MagicMock()
        project = MagicMock()

        extent = QgsRectangle(0, 0, 10, 10)
        canvas.extent.return_value = extent

        crs = MagicMock()
        canvas.mapSettings().destinationCrs.return_value = crs

        view_settings = MagicMock()
        project.viewSettings.return_value = view_settings

        mock_view = MagicMock()
        mock_ref_rect.return_value = mock_view

        _set_map_extent(canvas, project)

        mock_ref_rect.assert_called_once_with(extent, crs)
        view_settings.setDefaultViewExtent.assert_called_with(mock_view)
