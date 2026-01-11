from pathlib import Path
from qgis.core import QgsVectorLayer, QgsVectorFileWriter, QgsProject

from modules.geopackage import create_gpkg, check_existing_layer


def test_create_gpkg(tmp_path: Path) -> None:
    """Test creation of a new GeoPackage."""
    gpkg_path = tmp_path / "test.gpkg"

    assert not gpkg_path.exists()

    created_path = create_gpkg(gpkg_path)

    assert created_path.exists()
    assert created_path == gpkg_path


def test_check_existing_layer(tmp_path: Path, project: QgsProject) -> None:
    """Test logic for checking if a layer exists in the GPKG."""
    # 1. Setup GPKG
    gpkg_path = tmp_path / "data.gpkg"
    create_gpkg(gpkg_path)

    # 2. Create a layer and write it to the GPKG
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "MyLayer", "memory")
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "MyLayer"
    QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(gpkg_path), project.transformContext(), options
    )

    # 3. Test: Layer exists, same geometry -> Should return original name (overwrite)
    result_name = check_existing_layer(gpkg_path, layer)
    assert result_name == "MyLayer"

    # 4. Test: Layer exists, different geometry -> Should return new name with suffix
    # Create a Line layer with the same name
    line_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "MyLayer", "memory")
    result_name_line = check_existing_layer(gpkg_path, line_layer)

    # Expecting suffix for line (e.g., "MyLayer - l")
    assert result_name_line == "MyLayer - l"

    # 5. Test: Layer does not exist -> Should return original name
    new_layer = QgsVectorLayer("Point?crs=EPSG:4326", "NewLayer", "memory")
    result_name_new = check_existing_layer(gpkg_path, new_layer)
    assert result_name_new == "NewLayer"
