"""Enhanced integration tests for modules/geopackage.py."""

from pathlib import Path

from qgis.core import QgsProject, QgsVectorLayer

from modules.geopackage import (
    add_vector_layer_to_gpkg,
    check_existing_layer,
    create_gpkg,
)


class TestCheckExistingLayerEnhanced:
    """Enhanced tests for ``check_existing_layer``."""

    def test_special_characters_in_layer_name(self, tmp_gpkg: Path) -> None:
        """Test with layer names containing special characters."""
        create_gpkg(tmp_gpkg)
        # Semicolon is often used as a separator in URIs, let's see how it behaves.
        layer = QgsVectorLayer("Point?field=id:integer", "layer;name", "memory")
        assert layer.isValid()

        result = check_existing_layer(tmp_gpkg, layer)
        assert result == "layer;name"

    def test_double_suffix_prevention(self, tmp_gpkg: Path) -> None:
        """Test that appending a suffix doesn't double it if it already exists."""
        create_gpkg(tmp_gpkg)
        project = QgsProject.instance()

        # 1. Add a point layer named "my_layer"
        layer1 = QgsVectorLayer("Point", "my_layer", "memory")
        add_vector_layer_to_gpkg(project, layer1, tmp_gpkg)

        # 2. Now try to add a line layer also named "my_layer"
        # It should get a suffix, e.g. "my_layer - l"
        layer2 = QgsVectorLayer("LineString", "my_layer", "memory")
        result2 = check_existing_layer(tmp_gpkg, layer2)
        assert result2.endswith(" - l")

        # Manually add it with that name to the GPKG for the next step
        layer2.setName(result2)
        add_vector_layer_to_gpkg(project, layer2, tmp_gpkg)

        # 3. Now try to add ANOTHER line layer named "my_layer - l"
        # It should NOT become "my_layer - l - l"
        layer3 = QgsVectorLayer("LineString", result2, "memory")
        # Since it's the SAME geometry type as the one already in GPKG,
        # it should allow overwrite (return original name).
        result3 = check_existing_layer(tmp_gpkg, layer3)
        assert result3 == result2

        # 4. But if we try to add a POINT layer named "my_layer - l"
        # It should get a suffix "my_layer - l - pt" or "my_layer - pt"
        # The logic in geopackage.py:164 strips suffixes before adding a new one.
        layer4 = QgsVectorLayer("Point", result2, "memory")
        result4 = check_existing_layer(tmp_gpkg, layer4)
        # GEOMETRY_SUFFIX_MAP[Point] is 'pt'
        assert result4 == "my_layer - pt"

    def test_spaces_in_gpkg_path(self, tmp_path: Path) -> None:
        """Test that it works when the GeoPackage path contains spaces."""
        gpkg_with_space = tmp_path / "my folder" / "test project.gpkg"
        gpkg_with_space.parent.mkdir()
        create_gpkg(gpkg_with_space)

        layer = QgsVectorLayer("Point", "test_layer", "memory")
        result = check_existing_layer(gpkg_with_space, layer)
        assert result == "test_layer"
