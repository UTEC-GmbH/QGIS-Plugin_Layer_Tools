"""Integration tests for the shipping module (full flow)."""

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgisInterface

from modules.constants import ActionResults
from modules.shipping import prepare_layers_for_shipping


@pytest.mark.usefixtures("qgis_iface")
class TestShippingIntegration:
    """Integration tests for the full shipping process."""

    def test_prepare_layers_for_shipping(
        self, qgis_iface: QgisInterface, tmp_path: Path
    ) -> None:
        """Test the full flow of preparing layers for shipping."""
        # 1. Setup project with a vector layer and save it
        project = QgsProject.instance()
        project.clear()
        project_path = tmp_path / "shipping_project.qgs"
        project.setFileName(str(project_path))

        layer = QgsVectorLayer("Point?field=id:integer", "shipping_layer", "memory")
        project.addMapLayer(layer)
        project.write()

        # Select the layer
        qgis_iface.setActiveLayer(layer)

        # 2. Mock PluginContext project_path to return our tmp project
        with (
            patch("modules.shipping.get_selected_layers") as mock_selected,
            patch("modules.shipping.create_gpkg") as mock_create,
            patch("modules.shipping.add_layers_to_gpkg") as mock_add_to,
            patch("modules.shipping.add_layers_from_gpkg_to_project") as mock_add_from,
            patch("modules.shipping.PluginContext.project_path") as mock_p_path,
        ):
            mock_selected.return_value = [layer]
            mock_p_path.return_value = project_path

            # Mock create_gpkg to return a path
            dummy_gpkg = tmp_path / "dummy.gpkg"
            mock_create.return_value = dummy_gpkg

            # Mock add_layers_to_gpkg to return ActionResults
            mock_add_to.return_value = ActionResults(
                result={}, successes=["shipping_layer"]
            )

            # Need to mock this to avoid real project manipulation
            mock_add_from.return_value = ActionResults(result=None)

            prepare_layers_for_shipping()

            mock_create.assert_called()
            mock_add_to.assert_called()

    def test_prepare_layers_no_mock(
        self, qgis_iface: QgisInterface, tmp_path: Path
    ) -> None:
        """Test the full flow without mocking core logic."""
        project = QgsProject.instance()
        project.clear()
        project_path = tmp_path / "real_shipping.qgs"
        project.setFileName(str(project_path))

        layer = QgsVectorLayer("Point?field=id:integer", "real_layer", "memory")
        project.addMapLayer(layer)
        project.write()

        # Mock only the selection because setActiveLayer might
        # not be enough for get_selected_layers
        with patch("modules.shipping.get_selected_layers", return_value=[layer]):
            results: Any = prepare_layers_for_shipping()

            assert results is not None
            assert len(results.successes) == 1
            assert results.successes[0] == "real_layer"

            # Check if target GPKG was created
            date_str = datetime.now().astimezone().strftime("%Y_%m_%d")
            expected_gpkg = tmp_path / "Shipping" / f"real_shipping_{date_str}.gpkg"
            assert expected_gpkg.exists()
