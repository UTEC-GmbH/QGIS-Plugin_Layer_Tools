"""Module: functions_geopackage.py

This module contains the functions concerning GeoPackages.
"""

import contextlib
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from osgeo import ogr
from qgis.core import (
    Qgis,
    QgsLayerTree,
    QgsMapLayer,
    QgsProject,
    QgsRasterDataProvider,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication

from .constants import GEOMETRY_SUFFIX_MAP, LAYER_TYPES
from .context import PluginContext
from .general import (
    clear_attribute_table,
    get_selected_layers,
)
from .logs_and_errors import (
    log_debug,
    log_summary_message,
    raise_runtime_error,
)
from .rename import geometry_type_suffix

if TYPE_CHECKING:
    from qgis.core import QgsMapLayerStyle, QgsMapLayerStyleManager


def create_gpkg(
    gpkg_path: Path | None = None, *, delete_existing: bool = False
) -> Path:
    """Check if the GeoPackage exists and create an empty one if not.

    :param gpkg_path: The path to the GeoPackage.
    """

    if gpkg_path is None:
        gpkg_path = PluginContext.project_gpkg()

    if gpkg_path.exists():
        log_debug(f"Existing GeoPackage found in \n'{gpkg_path}'")
        if not delete_existing:
            return gpkg_path

    log_debug(f"Creating empty GeoPackage \n'{gpkg_path}'...")

    driver = ogr.GetDriverByName("GPKG")
    ds = driver.CreateDataSource(str(gpkg_path))
    if ds is None:
        raise_runtime_error(f"Could not create GeoPackage at \n'{gpkg_path}'")
    # close datasource to flush file
    ds = None

    return gpkg_path


def check_existing_layer(gpkg_path: Path, layer: QgsMapLayer) -> str:
    """Check if a layer with the same name and geometry type exists in the GeoPackage.

    If a layer with the same name but different geometry type exists, a new
    unique name is returned by appending a geometry suffix. If a layer with
    the same name and geometry type exists, the original name is returned to
    allow overwriting.

    :param gpkg_path: The path to the GeoPackage.
    :param layer: The layer to check for existence.
    :returns: A layer name for the GeoPackage. This will be the original name
              if no layer with that name exists, or if a layer with the same
              name and geometry type exists (allowing overwrite). It will be a
              new name with a suffix if a layer with the same name but
              different geometry type exists.
    """
    if not isinstance(layer, QgsVectorLayer):
        return layer.name()

    layer_name: str = layer.name()

    # Check if the layer exists in the GeoPackage using sqlite3 directly
    # to avoid QGIS warnings about missing layers and OGR errors on empty GPKGs.
    layer_exists = False
    with contextlib.suppress(sqlite3.Error), sqlite3.connect(str(gpkg_path)) as conn:
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (layer_name,),
        )
        if cursor.fetchone():
            layer_exists = True
    if not layer_exists:
        # Layer does not exist, safe to use original name.
        return layer_name

    uri: str = f"{gpkg_path}|layername={layer_name}"
    gpkg_layer = QgsVectorLayer(uri, layer_name, "ogr")

    if not gpkg_layer.isValid():
        return layer_name

    # A layer with the same name exists. Check geometry types.
    incoming_geom_type: Qgis.GeometryType = QgsWkbTypes.geometryType(layer.wkbType())
    existing_geom_type: Qgis.GeometryType = QgsWkbTypes.geometryType(
        gpkg_layer.wkbType()
    )

    if incoming_geom_type == existing_geom_type:
        # Name and geometry match, so we can overwrite. Return original name.
        return layer_name

    # Name matches but geometry is different. Create a new name with a suffix.
    # First, strip any existing geometry suffix from the layer name to get a
    # base name to prevent creating names with double suffixes (e.g., 'layer-pt-pt').
    suffix_values: str = "|".join([*list(GEOMETRY_SUFFIX_MAP.values()), "pl"])
    suffix_pattern: str = rf"\s-\s({suffix_values})$"
    base_name: str = re.sub(suffix_pattern, "", layer_name)

    return f"{base_name}{geometry_type_suffix(layer)}"


def add_vector_layer_to_gpkg(
    project: QgsProject, layer: QgsMapLayer, gpkg_path: Path
) -> tuple:
    """Add a vector layer to the GeoPackage.

    :param layer: The layer to add.
    :param gpkg_path: The path to the GeoPackage.
    """

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = check_existing_layer(gpkg_path, layer)
    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

    return QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(gpkg_path), project.transformContext(), options
    )


def add_raster_layer_to_gpkg(
    project: QgsProject, layer: QgsMapLayer, gpkg_path: Path
) -> dict[str, str | None]:
    """Add a raster layer to the GeoPackage using QgsRasterFileWriter.

    Args:
        layer: The layer to add.
        gpkg_path: The path to the GeoPackage.

    Returns:
        A dictionary with the result. The 'error' key will be None on
        success or contain an error message on failure.
    """

    if not isinstance(layer, QgsRasterLayer):
        return {"error": "Layer is not a valid raster layer.", "OUTPUT": None}

    provider: QgsRasterDataProvider | None = layer.dataProvider()
    if not provider:
        return {"error": "Could not get raster data provider.", "OUTPUT": None}

    layer_name: str = check_existing_layer(gpkg_path, layer)

    writer = QgsRasterFileWriter(str(gpkg_path))
    writer.setOutputFormat("GPKG")

    options: dict[str, str] = {
        "RASTER_TABLE": layer_name,
        "APPEND_SUBDATASET": "YES",
        "USE_GPKG_METADATA_TABLES": "YES",
    }
    create_options: list[str] = [f"{k}={v}" for k, v in options.items()]
    writer.setCreateOptions(create_options)

    pipe = QgsRasterPipe()
    pipe.set(provider.clone())
    error: QgsRasterFileWriter.WriterError = writer.writeRaster(
        pipe,
        layer.width(),
        layer.height(),
        layer.extent(),
        layer.crs(),
        project.transformContext(),
    )

    if error == QgsRasterFileWriter.WriterError.NoError:
        log_debug(f"Raster Layer '{layer_name}' added to GeoPackage.")
        return {"error": None, "OUTPUT": str(gpkg_path)}

    log_debug(
        f"Failed to add raster layer '{layer_name}' to GeoPackage. Error: {error}"
    )
    return {"error": error, "OUTPUT": None}


def clear_autocad_attributes(layer: QgsMapLayer, gpkg_path: Path) -> None:
    """Clear all AutoCAD attributes from a layer's attribute table.

    :param layer: The layer to clear AutoCAD attributes from.
    """

    uri: str = f"{gpkg_path}|layername={layer.name()}"
    gpkg_layer = QgsVectorLayer(uri, layer.name(), "ogr")
    if gpkg_layer.isValid() and isinstance(layer, QgsVectorLayer):
        is_autocad_import: bool = all(
            s in layer.source().lower()
            for s in ["|subset=layer", " and space=", " and block="]
        )
        if is_autocad_import:
            log_debug(
                f"AutoCAD import detected for layer '{layer.name()}'. "
                "Clearing attribute table."
            )
            clear_attribute_table(gpkg_layer)
    else:
        log_debug(f"Could not reload layer '{layer.name()}' from GeoPackage.")


def add_layers_to_gpkg(
    layers: list[QgsMapLayer] | None = None, gpkg_path: Path | None = None
) -> dict:
    """Add the selected layers to the project's GeoPackage.

    :param gpkg_path: Optional path to the GeoPackage. If not provided, the project's
                      default GeoPackage is used.
    :param layers: Optional list of layers to add. If not provided, the currently
                   selected layers are used.
    :returns: A dictionary containing the results of the operation, including
              successes, failures, and a mapping of original layers to their
              names in the GeoPackage.
    """

    project: QgsProject = PluginContext.project()
    if gpkg_path is None:
        gpkg_path = PluginContext.project_gpkg()

    if not gpkg_path.exists():
        raise_runtime_error(f"GeoPackage does not exist at '{gpkg_path}'")

    results: dict = {"successes": 0, "failures": [], "layer_mapping": {}}
    if layers is None:
        layers = get_selected_layers()
    for layer in layers:
        if "url=" in layer.source():
            log_debug(f"Layer '{layer.name()}' is a web service. Skipping.")
            results["successes"] += 1
            results["layer_mapping"][layer] = layer.name()
            continue

        layer_name: str = check_existing_layer(gpkg_path, layer)

        log_debug(
            f"Adding layer '{layer.name()}' (layer_name: '{layer_name}') "
            f"of type {LAYER_TYPES.get(layer.type(), layer.type())}' "
            f"to GeoPackage '{gpkg_path.name}'..."
        )

        if isinstance(layer, QgsVectorLayer):
            error: tuple = add_vector_layer_to_gpkg(project, layer, gpkg_path)
            if error[0] == QgsVectorFileWriter.WriterError.NoError:
                results["successes"] += 1
                results["layer_mapping"][layer] = layer_name
                clear_autocad_attributes(layer, gpkg_path)
                log_debug(
                    f"Layer '{layer.name()}' added to "
                    f"GeoPackage '{gpkg_path.name}' successfully."
                )
            else:
                results["failures"].append((layer.name(), error[1]))
                log_debug(f"Failed to add layer '{layer.name()}': {error[1]}")

        elif isinstance(layer, QgsMapLayer) and layer.type() == QgsMapLayer.RasterLayer:
            raster_results: dict = add_raster_layer_to_gpkg(project, layer, gpkg_path)
            if raster_results["OUTPUT"]:
                results["successes"] += 1
                results["layer_mapping"][layer] = layer_name
                log_debug(
                    f"Layer '{layer.name()}' added to "
                    f"GeoPackage '{gpkg_path.name}' successfully."
                )
            else:
                results["failures"].append((layer.name(), raster_results["error"]))
                log_debug(
                    f"Failed to add layer '{layer.name()}': {raster_results['error']}"
                )
        else:
            results["failures"].append((layer.name(), "Unsupported layer type."))
            log_debug(f"Failed to add layer '{layer.name()}': Unsupported layer type.")

    log_summary_message(
        successes=results["successes"],
        failures=results["failures"],
        action="Added to GeoPackage",
    )

    return results


def copy_layer_style(source_layer: QgsMapLayer, target_layer: QgsMapLayer) -> None:
    """Copy the active style from a source layer to a target layer.

    This function retrieves the currently active style from the `source_layer`,
    adds it to the `target_layer`'s style manager under the name
    'copied_style', and then sets this new style as the current one for the
    target layer. Finally, it triggers a repaint to ensure the changes are
    visible in the QGIS interface.

    Args:
        source_layer: The QGIS layer from which to copy the style.
        target_layer: The QGIS layer to which the style will be applied.
    """

    mngr_source: QgsMapLayerStyleManager | None = source_layer.styleManager()
    mngr_target: QgsMapLayerStyleManager | None = target_layer.styleManager()

    if mngr_source is None or mngr_target is None:
        return

    # get the name of the source layer's current style
    style_name: str = mngr_source.currentStyle()

    # get the style by the name
    style: QgsMapLayerStyle = mngr_source.style(style_name)

    # add the style to the target layer with a custom name (in this case: 'copied')
    mngr_target.addStyle("copied_style", style)

    # set the added style as the current style
    mngr_target.setCurrentStyle("copied_style")

    # propogate the changes to the QGIS GUI
    target_layer.triggerRepaint()
    target_layer.emitStyleChanged()


def _initialize_parameters(
    project: QgsProject | None,
    layers: list[QgsMapLayer] | None,
    gpkg_path: Path | None,
) -> tuple[QgsProject, list[QgsMapLayer], Path]:
    """Initialize and return the project, layers, and GeoPackage path.

    Args:
        project: The QGIS project instance.
        layers: A list of layers to process.
        gpkg_path: The path to the GeoPackage file.

    Returns:
        A tuple containing the initialized project, layers, and gpkg_path.
    """
    if project is None:
        project = PluginContext.project()
    if layers is None:
        layers = get_selected_layers()
    if gpkg_path is None:
        gpkg_path = PluginContext.project_gpkg()
    return project, layers, gpkg_path


def _handle_web_service_layer(
    layer_to_find: QgsMapLayer, layer_name: str, project: QgsProject
) -> QgsMapLayer | None:
    """Handle cloning and adding a web service layer.

    Checks if a layer with the same source and name already exists.

    Args:
        layer_to_find: The original web service layer.
        layer_name: The target name for the new layer.
        project: The current QGIS project.

    Returns:
        A cloned QgsMapLayer, or None if it already exists.
    """
    layer_exists: bool = any(
        existing_layer.source() == layer_to_find.source()
        and existing_layer.name() == layer_name
        for existing_layer in project.mapLayers().values()
    )

    if layer_exists:
        log_debug(
            f"Web service layer '{layer_name}' with the same source "
            "already exists. Skipping.",
            Qgis.Info,
        )
        return None

    gpkg_layer: QgsMapLayer | None = layer_to_find.clone()
    if gpkg_layer:
        gpkg_layer.setName(layer_name)
        log_debug(f"Web service layer '{layer_name}' cloned.")
    return gpkg_layer


def _create_layer_from_source(
    layer_to_find: QgsMapLayer,
    layer_name: str,
    gpkg_path_str: str,
    project: QgsProject,
) -> tuple[QgsMapLayer | None, str]:
    """Create a QgsMapLayer from its source (GPKG or web service).

    Args:
        layer_to_find: The original layer to be loaded.
        layer_name: The name of the layer in the GeoPackage or for the clone.
        gpkg_path_str: The string representation of the GeoPackage path.
        project: The current QGIS project.

    Returns:
        A tuple containing the new QgsMapLayer (or None) and its URI string.
    """
    uri = ""
    if "url=" in layer_to_find.source():
        return _handle_web_service_layer(layer_to_find, layer_name, project), uri

    if isinstance(layer_to_find, QgsRasterLayer):
        uri = f"GPKG:{gpkg_path_str}:{layer_name}"
        return QgsRasterLayer(uri, layer_name, "gdal"), uri

    uri = f"{gpkg_path_str}|layername={layer_name}"
    return QgsVectorLayer(uri, layer_name, "ogr"), uri


def add_layers_from_gpkg_to_project(
    gpkg_path: Path | None = None,
    project: QgsProject | None = None,
    layers: list[QgsMapLayer] | None = None,
    layer_mapping: dict[QgsMapLayer, str] | None = None,
) -> None:
    """Add the selected layers from the project's GeoPackage.

    :param gpkg_path: Optional path to the GeoPackage.
    :param project: Optional project to add layers to.
    :param layers: Optional list of layers to add.
    :param layer_mapping: Optional mapping of original layer objects to their
                          names in the GeoPackage.
    """
    project, layers, gpkg_path = _initialize_parameters(project, layers, gpkg_path)

    root: QgsLayerTree | None = project.layerTreeRoot()
    if not root:
        msg = QCoreApplication.translate(
            "RuntimeError", "Could not get layer tree root."
        )
        raise_runtime_error(msg)

    added_layers: list[str] = []
    not_found_layers: list[str] = []
    gpkg_path_str = str(gpkg_path)

    for layer_to_find in layers:
        layer_name = (
            layer_mapping.get(layer_to_find, layer_to_find.name())
            if layer_mapping
            else layer_to_find.name()
        )

        gpkg_layer, uri = _create_layer_from_source(
            layer_to_find, layer_name, gpkg_path_str, project
        )

        if not gpkg_layer:
            # Layer was skipped (e.g., web layer already exists)
            continue

        if not gpkg_layer.isValid():
            not_found_layers.append(layer_name)
            msg = f"Layer '{layer_name}' not found in GeoPackage."
            if uri:
                msg += f"\nlooked for: {uri}"
            log_debug(msg, Qgis.Warning)
            continue

        project.addMapLayer(gpkg_layer, addToLegend=False)
        root.insertLayer(0, gpkg_layer)
        added_layers.append(layer_name)

        # Cloned web layers already have their style.
        if "url=" not in layer_to_find.source():
            copy_layer_style(layer_to_find, gpkg_layer)

    if added_layers:
        log_debug(
            f"Added '{len(added_layers)}' layer(s) from the GeoPackage to the project.",
            Qgis.Success,
        )
    if not_found_layers:
        log_debug(
            f"Could not find {len(not_found_layers)} layer(s) "
            f"in GeoPackage: {', '.join(not_found_layers)}",
            Qgis.Warning,
        )

    log_summary_message(
        successes=len(added_layers),
        failures=not_found_layers,
        action="Added from GeoPackage",
    )


def move_layers_to_gpkg() -> None:
    """Move the selected layers to the project's GeoPackage."""

    results = add_layers_to_gpkg()
    add_layers_from_gpkg_to_project(layer_mapping=results.get("layer_mapping"))
