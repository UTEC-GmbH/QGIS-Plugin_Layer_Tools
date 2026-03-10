"""Integration tests for the browser module in a QGIS environment."""

from pathlib import Path

import pytest
from qgis.core import QgsProject, QgsVectorFileWriter, QgsVectorLayer

from modules.browser import GeopackageProxyModel, ProjectGpkgDataItem


@pytest.mark.usefixtures("qgis_iface")
class TestBrowserIntegration:
    """Integration tests for browser customization."""

    def test_proxy_model_icons(self) -> None:
        """Test that the proxy model returns appropriate icons."""
        model = GeopackageProxyModel()
        icon = model._create_composite_icon(model.icon_gpkg, model.icon_used)
        assert icon is not None
        assert not icon.isNull()

    def test_project_gpkg_item_children(self, tmp_path: Path) -> None:
        """Test that ProjectGpkgDataItem creates children from a GeoPackage."""
        gpkg_path = tmp_path / "test.gpkg"
        # Create a dummy gpkg with a table
        layer = QgsVectorLayer("Point?field=id:integer", "test_layer", "memory")

        QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            str(gpkg_path),
            QgsProject.instance().transformContext(),
            QgsVectorFileWriter.SaveVectorOptions(),
        )

        item = ProjectGpkgDataItem(None, "Test GPKG", gpkg_path)
        children = item.createChildren()

        assert len(children) >= 1
        assert children[0].name() == "test"
