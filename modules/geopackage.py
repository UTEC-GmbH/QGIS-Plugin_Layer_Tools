"""Module: geopackage.py

This module contains the functions concerning GeoPackages.
"""

import contextlib
import os
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
    QgsProviderRegistry,
    QgsRasterDataProvider,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QShowEvent
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .constants import GEOMETRY_SUFFIX_MAP, LAYER_TYPES, ActionResults, Issue
from .context import PluginContext
from .general import clear_attribute_table, get_selected_layers
from .logs_and_errors import log_debug, raise_runtime_error
from .rename import geometry_type_suffix

if TYPE_CHECKING:
    from qgis.core import QgsMapLayerStyle, QgsMapLayerStyleManager


def create_gpkg(
    gpkg_path: Path | None = None, *, delete_existing: bool = False
) -> Path:
    """Check if the GeoPackage exists and create an empty one if not.

    Args:
        gpkg_path: The path to the GeoPackage.
        delete_existing: Whether to delete the existing GeoPackage if it exists.

    Returns:
        Path: The path to the GeoPackage.
    """
    if gpkg_path is None:
        gpkg_path = PluginContext.project_gpkg()

    if gpkg_path.exists():
        log_debug(f"GeoPackage → Existing GeoPackage found in \n'{gpkg_path}'")
        if not delete_existing:
            return gpkg_path

    log_debug(f"GeoPackage → Creating empty GeoPackage \n'{gpkg_path}'...")

    driver = ogr.GetDriverByName("GPKG")
    ds = driver.CreateDataSource(str(gpkg_path))
    if ds is None:
        raise_runtime_error(f"Could not create GeoPackage at \n'{gpkg_path}'")
    # close datasource to flush file
    ds = None

    return gpkg_path


def _validate_gpkg_layer_name(name: str, existing_layers: set[str]) -> str | None:
    """Return a validation warning for a new GeoPackage table name, if any."""
    if not name or not name.strip():
        return QCoreApplication.translate("GeoPackage", "Enter a layer name.")
    if name != name.strip() or "\x00" in name:
        return QCoreApplication.translate("GeoPackage", "The layer name is invalid.")
    if name.casefold().startswith(("gpkg_", "sqlite_")):
        return QCoreApplication.translate(
            "GeoPackage", "Names starting with 'gpkg_' or 'sqlite_' are reserved."
        )
    if name.casefold() in {layer.casefold() for layer in existing_layers}:
        return QCoreApplication.translate(
            "GeoPackage", "A layer with this name already exists in the GeoPackage."
        )
    return None


class _NewGpkgLayerDialog(QDialog):
    """Dialog for naming a new GeoPackage vector table."""

    def __init__(
        self, existing_layers: set[str], parent: QWidget | None = None
    ) -> None:
        """Initialize the dialog with available geometry types."""
        super().__init__(parent)
        self.setWindowTitle(
            QCoreApplication.translate("GeoPackage", "Create New GeoPackage Layer")
        )
        self.setMinimumWidth(360)
        self.existing_layers = existing_layers

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.geometry_combo = QComboBox()
        for label, geometry in (
            ("Point", "Point"),
            ("Line", "LineString"),
            ("Polygon", "Polygon"),
        ):
            self.geometry_combo.addItem(
                QCoreApplication.translate("GeoPackage", label), geometry
            )
        self.geometry_combo.setCurrentIndex(self.geometry_combo.findData("Polygon"))
        form.addRow(
            QCoreApplication.translate("GeoPackage", "Geometry type:"),
            self.geometry_combo,
        )

        self.name_edit = QLineEdit()
        form.addRow(
            QCoreApplication.translate("GeoPackage", "Layer name:"), self.name_edit
        )

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.warning_label.setContentsMargins(0, 4, 0, 4)
        self.warning_label.setMinimumHeight(
            self.warning_label.fontMetrics().lineSpacing() * 3 + 8
        )
        form.addRow("", self.warning_label)
        layout.addLayout(form)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.name_edit.textChanged.connect(self._update_name_warning)
        self._update_name_warning(self.name_edit.text())

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Focus the layer name field as soon as the dialog is shown."""
        super().showEvent(event)
        self.name_edit.setFocus()

    def _update_name_warning(self, name: str) -> None:
        """Show live validation feedback and disable OK for invalid names."""
        warning = _validate_gpkg_layer_name(name, self.existing_layers)
        self.warning_label.setText(warning or "")
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(warning is None)

    def layer_name(self) -> str:
        """Return the entered layer name."""
        return self.name_edit.text()

    def geometry_type(self) -> str:
        """Return the selected memory-provider geometry type."""
        return self.geometry_combo.currentData()


def _create_gpkg_vector_layer(
    project: QgsProject,
    gpkg_path: Path,
    layer_name: str,
    geometry_type: str,
) -> QgsVectorLayer:
    """Create an empty GeoPackage table and add its layer to the project."""
    existing_layers = get_gpkg_layer_names(gpkg_path)
    if warning := _validate_gpkg_layer_name(layer_name, existing_layers):
        raise_runtime_error(warning)

    memory_layer = QgsVectorLayer(geometry_type, layer_name, "memory")
    if not memory_layer.isValid():
        raise_runtime_error(
            QCoreApplication.translate(
                "GeoPackage", "Could not create the temporary vector layer."
            )
        )
    memory_layer.setCrs(project.crs())

    create_gpkg(gpkg_path)
    result = add_vector_layer_to_gpkg(
        project, memory_layer, gpkg_path, existing_layers=existing_layers
    )
    if result.errors:
        raise_runtime_error(result.errors[0].issue)

    gpkg_layer = QgsVectorLayer(
        f"{gpkg_path}|layername={layer_name}", layer_name, "ogr"
    )
    if not gpkg_layer.isValid():
        raise_runtime_error(
            QCoreApplication.translate(
                "GeoPackage",
                "The new layer was written but could not be loaded into the project.",
            )
        )

    project.addMapLayer(gpkg_layer, False)
    if root := project.layerTreeRoot():
        root.insertLayer(0, gpkg_layer)
    iface = PluginContext.iface()
    iface.setActiveLayer(gpkg_layer)
    if layer_tree_view := iface.layerTreeView():
        layer_tree_view.setCurrentLayer(gpkg_layer)
    if not gpkg_layer.startEditing():
        raise_runtime_error(
            QCoreApplication.translate(
                "GeoPackage", "Could not start editing the new GeoPackage layer."
            )
        )
    log_debug(
        f"GeoPackage → Empty vector layer '{layer_name}' created.",
        Qgis.Success,
    )
    return gpkg_layer


def create_gpkg_layer() -> None:
    """Prompt for a name and geometry type, then create an empty GPKG layer."""
    gpkg_path = PluginContext.project_gpkg()
    project = PluginContext.project()
    dialog = _NewGpkgLayerDialog(
        get_gpkg_layer_names(gpkg_path), PluginContext.iface().mainWindow()
    )
    if dialog.exec() != QDialog.Accepted:
        return

    layer_name = dialog.layer_name()
    geometry_type = dialog.geometry_type()
    if warning := _validate_gpkg_layer_name(
        layer_name, get_gpkg_layer_names(gpkg_path)
    ):
        QMessageBox.warning(
            PluginContext.iface().mainWindow(),
            QCoreApplication.translate("GeoPackage", "Invalid Layer Name"),
            warning,
        )
        return
    _create_gpkg_vector_layer(project, gpkg_path, layer_name, geometry_type)


def _delete_gpkg_tables(gpkg_path: Path, layer_names: set[str]) -> None:
    """Delete vector and raster tables from a GeoPackage."""
    if not layer_names:
        return

    if not gpkg_path.exists():
        raise_runtime_error(
            QCoreApplication.translate(
                "GeoPackage", "The project's GeoPackage does not exist."
            )
        )

    with sqlite3.connect(str(gpkg_path)) as conn:
        cursor = conn.cursor()
        contents = {
            name.casefold(): (name, data_type)
            for name, data_type in cursor.execute(
                "SELECT table_name, data_type FROM gpkg_contents"
            )
        }

    requested = {name.casefold() for name in layer_names}
    missing = requested - contents.keys()
    if missing:
        raise_runtime_error(
            QCoreApplication.translate(
                "GeoPackage", "Could not find these tables in the GeoPackage: "
            )
            + ", ".join(sorted(missing))
        )

    vector_tables = {
        contents[key][0] for key in requested if contents[key][1] != "tiles"
    }
    raster_tables = {
        contents[key][0] for key in requested if contents[key][1] == "tiles"
    }

    if vector_tables:
        dataset = ogr.Open(str(gpkg_path), 1)
        if dataset is None:
            raise_runtime_error(
                QCoreApplication.translate(
                    "GeoPackage", "Could not open the GeoPackage for editing."
                )
            )
        for table_name in sorted(vector_tables):
            layer_index = next(
                (
                    index
                    for index in range(dataset.GetLayerCount())
                    if (layer := dataset.GetLayer(index))
                    and layer.GetName().casefold() == table_name.casefold()
                ),
                None,
            )
            if layer_index is None or dataset.DeleteLayer(layer_index) != 0:
                dataset = None
                raise_runtime_error(
                    QCoreApplication.translate(
                        "GeoPackage", "Could not delete GeoPackage table: "
                    )
                    + table_name
                )
        dataset = None

    if raster_tables:
        with sqlite3.connect(str(gpkg_path)) as conn:
            cursor = conn.cursor()
            existing_catalog_tables = {
                row[0]
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table_name in sorted(raster_tables):
                safe_name = table_name.replace('"', '""')
                for catalog_table, column in (
                    ("gpkg_extensions", "table_name"),
                    ("gpkg_tile_matrix", "table_name"),
                    ("gpkg_tile_matrix_set", "table_name"),
                    ("gpkg_metadata_reference", "table_name"),
                ):
                    if catalog_table in existing_catalog_tables:
                        cursor.execute(
                            f'DELETE FROM "{catalog_table}" WHERE "{column}" = ?',
                            (table_name,),
                        )
                cursor.execute(f'DROP TABLE "{safe_name}"')
                cursor.execute(
                    "DELETE FROM gpkg_contents WHERE table_name = ?", (table_name,)
                )


def delete_gpkg_layers() -> None:
    """Confirm and delete selected project layers and their GPKG tables."""
    selected_layers = get_selected_layers()
    gpkg_path = PluginContext.project_gpkg()
    project = PluginContext.project()
    selected_ids = {layer.id() for layer in selected_layers}
    selected_details_lines: list[str] = []
    for layer in selected_layers:
        source_table = _get_gpkg_layer_table(layer, gpkg_path)
        if source_table:
            source_detail = (
                f" (GeoPackage table: {source_table})"
                if source_table.casefold() != layer.name().casefold()
                else ""
            )
        else:
            source_detail = (
                QCoreApplication.translate(
                    "GeoPackage",
                    " (outside the project's GeoPackage; source will be kept: ",
                )
                + layer.source()
                + ")"
            )
        selected_details_lines.append(f"• {layer.name()}{source_detail}")
    selected_details = "\n".join(selected_details_lines)

    reply = QMessageBox.warning(
        PluginContext.iface().mainWindow(),
        QCoreApplication.translate("GeoPackage", "Delete Layers and Data Sources"),
        QCoreApplication.translate(
            "GeoPackage",
            "The selected layers and layers in selected groups will be deleted "
            "from the project. Corresponding tables in the project's GeoPackage "
            "will also be deleted; other data sources will not be changed.\n\n"
            "Selected layers:\n",
        )
        + selected_details,
        QMessageBox.Ok | QMessageBox.Cancel,
        QMessageBox.Cancel,
    )
    if reply != QMessageBox.Ok:
        return

    dependencies = _get_gpkg_layer_dependencies(gpkg_path)
    tables_to_delete = {
        table_name
        for table_name, layers in dependencies.items()
        if any(layer.id() in selected_ids for layer in layers)
    }
    affected_layers = {
        layer.id(): layer
        for table_name in tables_to_delete
        for layer in dependencies[table_name]
        if layer.id() not in selected_ids
    }

    if affected_layers:
        affected_details = "\n".join(
            f"• {layer.name()} (GeoPackage table: {table_name}; "
            f"source: {layer.source()})"
            for table_name in sorted(tables_to_delete)
            for layer in dependencies[table_name]
            if layer.id() not in selected_ids
        )
        dialog = _shared_source_warning_dialog(
            affected_details, PluginContext.iface().mainWindow()
        )
        if dialog.exec() != QMessageBox.Yes:
            return

    layer_count = len(selected_layers) + len(affected_layers)
    for layer in [*selected_layers, *affected_layers.values()]:
        project.removeMapLayer(layer.id())
    selected_layers.clear()
    affected_layers.clear()
    dependencies.clear()
    layer = None
    _delete_gpkg_tables(gpkg_path, tables_to_delete)
    log_debug(
        f"GeoPackage → Deleted {layer_count} "
        "project layer(s) and "
        f"{len(tables_to_delete)} GeoPackage table(s).",
        Qgis.Success,
    )


def _shared_source_warning_dialog(
    affected_details: str, parent: QWidget | None = None
) -> QMessageBox:
    """Build the confirmation dialog for deleting shared GeoPackage tables."""
    dialog = QMessageBox(
        QMessageBox.Warning,
        QCoreApplication.translate("GeoPackage", "Shared Data Source Warning"),
        QCoreApplication.translate(
            "GeoPackage",
            "These unselected project layers use a table that would be deleted:\n\n",
        )
        + affected_details
        + QCoreApplication.translate(
            "GeoPackage",
            "\n\nDelete these layers as well as the selected layers and "
            "their data sources?",
        ),
        QMessageBox.Yes | QMessageBox.Cancel,
        parent,
    )
    yes_button = dialog.button(QMessageBox.Yes)
    if yes_button is None:
        raise_runtime_error(
            QCoreApplication.translate(
                "GeoPackage", "Could not configure the shared-source warning dialog."
            )
        )
    yes_button.setText(
        QCoreApplication.translate("GeoPackage", "Delete All Affected Layers")
    )
    dialog.setDefaultButton(QMessageBox.Cancel)
    return dialog


def _get_gpkg_layer_table(layer: QgsMapLayer, gpkg_path: Path) -> str | None:
    """Return a layer's GeoPackage table when it uses this project GeoPackage."""
    registry = QgsProviderRegistry.instance()
    if not registry:
        return None

    source = layer.source()
    decoded = registry.decodeUri(layer.providerType(), source)
    source_path = decoded.get("path")
    table_name = decoded.get("layerName")

    gpkg_uri_match = re.match(r"(?i)^GPKG:(.+?\.gpkg):(.+)$", source)
    if gpkg_uri_match:
        source_path, table_name = gpkg_uri_match.groups()
    elif "|layername=" in source:
        source_path, table_name = source.split("|layername=", 1)
        table_name = table_name.split("|", 1)[0]
    else:
        dbname_match = re.search(
            r"""(?i)dbname=['"]?(.+?\.gpkg)['"]?\s+table=['"]?([^'"\s(]+)""",
            source,
        )
        if dbname_match:
            source_path, table_name = dbname_match.groups()

    if not isinstance(source_path, str) or not source_path:
        return None
    if not isinstance(table_name, str) or table_name.casefold() in {"", "null"}:
        return None

    source_path_obj = Path(source_path)
    project_file = PluginContext.project().fileName()
    if not source_path_obj.is_absolute() and project_file:
        source_path_obj = Path(project_file).parent / source_path_obj
    expected_path = Path(gpkg_path)
    try:
        normalized_source = os.path.normcase(str(source_path_obj.resolve()))
        normalized_expected = os.path.normcase(str(expected_path.resolve()))
    except OSError:
        normalized_source = os.path.normcase(os.path.abspath(source_path))
        normalized_expected = os.path.normcase(os.path.abspath(str(expected_path)))

    if normalized_source != normalized_expected:
        return None
    return table_name


def get_gpkg_layer_names(gpkg_path: Path) -> set[str]:
    """Get a set of all table names (layers) in a GeoPackage.

    Args:
        gpkg_path: The path to the GeoPackage.

    Returns:
        set[str]: A set of table names.
    """
    if not gpkg_path.exists():
        return set()

    with contextlib.suppress(sqlite3.Error), sqlite3.connect(str(gpkg_path)) as conn:
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in cursor.fetchall()}
    return set()


def check_existing_layer(
    gpkg_path: Path,
    layer: QgsMapLayer,
    existing_layers: set[str] | None = None,
) -> str:
    """Check if a layer with the same name and geometry type exists in the GeoPackage.

    If a layer with the same name but different geometry type exists, a new
    unique name is returned by appending a geometry suffix. If a layer with
    the same name and geometry type exists, the original name is returned to
    allow overwriting.

    Args:
        gpkg_path: The path to the GeoPackage.
        layer: The layer to check for existence.
        existing_layers: Optional set of existing layer names to avoid repeated I/O.

    Returns:
        str: A layer name for the GeoPackage. This will be the original name
             if no layer with that name exists, or if a layer with the same
             name and geometry type exists (allowing overwrite). It will be a
             new name with a suffix if a layer with the same name but
             different geometry type exists.
    """
    if not isinstance(layer, QgsVectorLayer):
        return layer.name()

    layer_name: str = layer.name()
    layer_exists: bool = False

    # Check if the layer exists
    if existing_layers is not None:
        layer_exists = layer_name in existing_layers
    else:
        # Fallback to single connection if no cache provided
        with (
            contextlib.suppress(sqlite3.Error),
            sqlite3.connect(str(gpkg_path)) as conn,
        ):
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

    # Check if we can overwrite (same geometry type)
    uri: str = f"{gpkg_path}|layername={layer_name}"
    gpkg_layer = QgsVectorLayer(uri, layer_name, "ogr")

    if gpkg_layer.isValid():
        incoming_geom_type: Qgis.GeometryType = QgsWkbTypes.geometryType(
            layer.wkbType()
        )
        existing_geom_type: Qgis.GeometryType = QgsWkbTypes.geometryType(
            gpkg_layer.wkbType()
        )

        if incoming_geom_type == existing_geom_type:
            # Name and geometry match, so we can overwrite. Return original name.
            return layer_name

    # Name matches but geometry is different (or layer invalid).
    # Create a new name with a suffix.
    # First, strip any existing geometry suffix from the layer name to get a
    # base name to prevent creating names with double suffixes (e.g., 'layer-pt-pt').
    suffix_values: str = "|".join([*list(GEOMETRY_SUFFIX_MAP.values()), "pl"])
    suffix_pattern: str = rf"\s-\s({suffix_values})$"
    base_name: str = re.sub(suffix_pattern, "", layer_name)

    return f"{base_name}{geometry_type_suffix(layer)}"


def add_vector_layer_to_gpkg(
    project: QgsProject,
    layer: QgsMapLayer,
    gpkg_path: Path,
    existing_layers: set[str] | None = None,
) -> ActionResults[tuple]:
    """Add a vector layer to the GeoPackage.

    Args:
        project: The QGIS project instance.
        layer: The layer to add.
        gpkg_path: The path to the GeoPackage.
        existing_layers: Optional set of existing layer names.

    Returns:
        ActionResults: An object containing the result tuple from QgsVectorFileWriter
            and success/error information.
    """
    layer_name: str = layer.name()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = check_existing_layer(gpkg_path, layer, existing_layers)
    if PluginContext.is_qgis4():
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        )
    else:
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

    result_write: tuple = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(gpkg_path), project.transformContext(), options
    )

    if PluginContext.is_qgis4():
        success = result_write[0] == QgsVectorFileWriter.WriterError.NoError
    else:
        success = result_write[0] == QgsVectorFileWriter.NoError

    if success:
        log_debug(
            f"GeoPackage → Vector Layer '{layer_name}' "
            "added to GeoPackage successfully.",
            Qgis.Success,
        )
        return ActionResults(result_write, successes=[layer_name])

    log_debug(
        f"GeoPackage → Failed to add vector layer '{layer_name}' to GeoPackage.",
        Qgis.Critical,
    )
    return ActionResults(
        result_write,
        errors=[
            Issue(
                layer_name,
                f"Failed to add vector layer to GeoPackage: {result_write[1]}",
            )
        ],
    )


def add_raster_layer_to_gpkg(
    project: QgsProject,
    layer: QgsMapLayer,
    gpkg_path: Path,
    existing_layers: set[str] | None = None,
) -> ActionResults[str | None]:
    """Add a raster layer to the GeoPackage using QgsRasterFileWriter.

    Args:
        project: The QGIS project instance.
        layer: The layer to add.
        gpkg_path: The path to the GeoPackage.
        existing_layers: Optional set of existing layer names.

    Returns:
        ActionResults: An object containing the result (path to gpkg on success),
            successes, and errors.
    """
    if not isinstance(layer, QgsRasterLayer):
        return ActionResults(
            None,
            errors=[
                Issue(
                    layer.name(),
                    "Failed to add raster layer to GeoPackage: "
                    "not a valid raster layer.",
                )
            ],
        )

    provider: QgsRasterDataProvider | None = layer.dataProvider()
    if not provider:
        raise_runtime_error("Could not get raster data provider.")

    layer_name: str = check_existing_layer(gpkg_path, layer, existing_layers)

    # Ensure clean overwrite by dropping existing raster table
    with contextlib.suppress(sqlite3.Error), sqlite3.connect(str(gpkg_path)) as conn:
        cursor: sqlite3.Cursor = conn.cursor()
        safe_name: str = layer_name.replace('"', '""')
        cursor.execute(f'DROP TABLE IF EXISTS "{safe_name}"')

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

    if PluginContext.is_qgis4():
        success = error == QgsRasterFileWriter.WriterError.NoError
    else:
        success = error == QgsRasterFileWriter.NoError

    if success:
        log_debug(
            f"GeoPackage → Raster Layer '{layer_name}' added to GeoPackage.",
            Qgis.Success,
        )
        return ActionResults(str(gpkg_path), successes=[layer_name])

    log_debug(
        f"GeoPackage → Failed to add raster layer '{layer_name}' to GeoPackage. "
        f"Error: {error}",
        Qgis.Critical,
    )
    return ActionResults(
        None,
        errors=[
            Issue(layer_name, f"Failed to add raster layer to GeoPackage: {error}")
        ],
    )


def clear_autocad_attributes(layer: QgsMapLayer, gpkg_path: Path) -> None:
    """Clear all AutoCAD attributes from a layer's attribute table.

    Args:
        layer: The layer to clear AutoCAD attributes from.
        gpkg_path: The path to the GeoPackage.
    """
    layer_name: str = layer.name()
    uri: str = f"{gpkg_path}|layername={layer_name}"
    gpkg_layer = QgsVectorLayer(uri, layer_name, "ogr")
    if gpkg_layer.isValid() and isinstance(layer, QgsVectorLayer):
        is_autocad_import: bool = all(
            s in layer.source().lower()
            for s in ["|subset=layer", " and space=", " and block="]
        )
        if is_autocad_import:
            log_debug(
                f"GeoPackage → AutoCAD import detected for layer '{layer_name}'. "
                "Clearing attribute table."
            )
            clear_attribute_table(gpkg_layer)
    else:
        log_debug(
            f"GeoPackage → Could not reload layer '{layer_name}' from GeoPackage.",
            Qgis.Warning,
        )


def _get_gpkg_layer_dependencies(
    gpkg_path: Path,
) -> dict[str, list[QgsMapLayer]]:
    """Get a mapping of GeoPackage tables to project layers that use them.

    Args:
        gpkg_path: The path to the GeoPackage.

    Returns:
        dict[str, list[QgsMapLayer]]: A mapping of table names to the project
        layers that use those tables.
    """
    dependencies: dict[str, list[QgsMapLayer]] = {}
    project: QgsProject = PluginContext.project()
    registry: QgsProviderRegistry | None = QgsProviderRegistry.instance()

    if not registry:
        return dependencies

    for layer in project.mapLayers().values():
        if table_name := _get_gpkg_layer_table(layer, gpkg_path):
            dependencies.setdefault(table_name, []).append(layer)

    return dependencies


def _confirm_overwrites(
    layers: list[QgsMapLayer], gpkg_path: Path, existing_layers: set[str]
) -> bool:
    """Check for overwrites and ask user for confirmation if necessary.

    Confirmation is only requested if a layer that is about to be overwritten
    is currently used as a data source by a layer in the project.

    Args:
        layers: The list of layers to be added.
        gpkg_path: The path to the GeoPackage.
        existing_layers: A set of existing layer names in the GeoPackage.

    Returns:
        bool: True if the operation should proceed, False otherwise.
    """
    potential_overwrites: set[str] = set()

    for layer in layers:
        if "url=" in layer.source():
            continue

        # Determine the name the layer will have in the GPKG
        target_name: str = check_existing_layer(gpkg_path, layer, existing_layers)

        if target_name in existing_layers:
            potential_overwrites.add(target_name)

    if not potential_overwrites:
        return True

    # Found overwrites, check which ones are used as dependencies in the project
    dependencies: dict[str, list[QgsMapLayer]] = _get_gpkg_layer_dependencies(gpkg_path)
    used_overwrites: set[str] = {
        table for table in potential_overwrites if table in dependencies
    }

    if not used_overwrites:
        return True

    # fmt: off
    msg: str = QCoreApplication.translate("GeoPackage", "The following layers in the project's GeoPackage are currently in use in the project and will be overwritten:\n",  # noqa: E501
    )
    # fmt: on

    for table in sorted(used_overwrites):
        msg += f"\n• {table}"
        if deps := dependencies.get(table):
            dep_str: str = ", ".join(layer.name() for layer in deps)
            usage_text = QCoreApplication.translate("GeoPackage", "used by")
            msg += f" ({usage_text}: {dep_str})"

    # fmt: off
    msg += QCoreApplication.translate("GeoPackage", "\n\nThis can lead to to unexpected results (especially if used by multiple layers). \n\nDo you want to continue?")  # noqa: E501
    # fmt: on

    reply = QMessageBox.question(
        PluginContext.iface().mainWindow(),
        QCoreApplication.translate("GeoPackage", "Overwrite Warning"),
        msg,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )

    return reply == QMessageBox.Yes


def add_layers_to_gpkg(
    layers: list[QgsMapLayer] | None = None, gpkg_path: Path | None = None
) -> ActionResults[dict[QgsMapLayer, str]]:
    """Add the selected layers to the project's GeoPackage.

    Args:
        layers: Optional list of layers to add. If not provided, the currently
            selected layers are used.
        gpkg_path: Optional path to the GeoPackage. If not provided, the project's
            default GeoPackage is used.

    Returns:
        ActionResults: An object containing the results of the operation.
            The .result attribute contains a dictionary mapping original layers
            to their names in the GeoPackage.
    """
    project: QgsProject = PluginContext.project()
    if gpkg_path is None:
        gpkg_path = PluginContext.project_gpkg()

    create_gpkg(gpkg_path)

    if layers is None:
        layers = get_selected_layers()

    # Pre-fetch existing layer names to avoid repeated DB connections
    existing_layers: set[str] = get_gpkg_layer_names(gpkg_path)

    if not _confirm_overwrites(layers, gpkg_path, existing_layers):
        return ActionResults(
            {}, errors=[Issue("User Cancelled", "Operation cancelled by user.")]
        )

    results: ActionResults[dict[QgsMapLayer, str]] = ActionResults({})

    for layer in layers:
        layer_name: str = layer.name()
        results.processed.append(layer_name)

        if "url=" in layer.source():
            log_debug(f"GeoPackage → Layer '{layer_name}' is a web service. Skipping.")
            results.result[layer] = layer_name
            results.skips.append(
                Issue(layer_name, "Layer is a web service → not added to GeoPackage.")
            )
            continue

        # change layer name if necessary
        layer_name: str = check_existing_layer(gpkg_path, layer, existing_layers)

        log_debug(
            f"GeoPackage → Adding layer '{layer_name}' "
            f"of type {LAYER_TYPES.get(layer.type(), 'unknown')}' "
            f"to GeoPackage '{gpkg_path.name}'..."
        )

        if isinstance(layer, QgsVectorLayer):
            add_layer_result: ActionResults[tuple] = add_vector_layer_to_gpkg(
                project, layer, gpkg_path, existing_layers
            )
            # Logging handled in add_vector_layer_to_gpkg
            if add_layer_result.successes:
                results.successes.append(layer_name)
                results.result[layer] = layer_name
                existing_layers.add(layer_name)
                clear_autocad_attributes(layer, gpkg_path)
            else:
                results.errors.extend(add_layer_result.errors)

        elif isinstance(layer, QgsRasterLayer):
            raster_results: ActionResults[str | None] = add_raster_layer_to_gpkg(
                project, layer, gpkg_path, existing_layers
            )
            # Logging handled in add_raster_layer_to_gpkg
            if raster_results.successes:
                results.successes.append(layer_name)
                results.result[layer] = layer_name
                existing_layers.add(layer_name)
            else:
                results.errors.extend(raster_results.errors)
        else:
            results.errors.append(
                Issue(
                    layer_name,
                    "Failed to add layer to GeoPackage: Unsupported layer type.",
                )
            )
            log_debug(
                f"GeoPackage → Failed to add layer '{layer_name}' to GeoPackage: "
                f"Unsupported layer type '{layer.type()}'.",
                Qgis.Critical,
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
            f"GeoPackage → Web service layer '{layer_name}' with the same source "
            "already exists. Skipping."
        )
        return None

    gpkg_layer: QgsMapLayer | None = layer_to_find.clone()
    if gpkg_layer:
        gpkg_layer.setName(layer_name)
        log_debug(
            f"GeoPackage → Web service layer '{layer_name}' cloned.", Qgis.Success
        )
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
    uri: str = ""
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
) -> ActionResults[None]:
    """Add the selected layers from the project's GeoPackage.

    Args:
        gpkg_path: Optional path to the GeoPackage.
        project: Optional project to add layers to.
        layers: Optional list of layers to add.
        layer_mapping: Optional mapping of original layer objects to their
            names in the GeoPackage.

    Returns:
        ActionResults: An object containing the results of the operation.
    """
    project, layers, gpkg_path = _initialize_parameters(project, layers, gpkg_path)

    root: QgsLayerTree | None = project.layerTreeRoot()
    if not root:
        # fmt: off
        msg: str = QCoreApplication.translate("RuntimeError", "Could not get layer tree root.")  # noqa: E501
        # fmt: on
        raise_runtime_error(msg)

    results: ActionResults[None] = ActionResults(None)
    gpkg_path_str = str(gpkg_path)

    for layer_to_find in layers:
        layer_name: str = (
            layer_mapping.get(layer_to_find, layer_to_find.name())
            if layer_mapping
            else layer_to_find.name()
        )
        results.processed.append(layer_name)

        gpkg_layer, uri = _create_layer_from_source(
            layer_to_find, layer_name, gpkg_path_str, project
        )

        if not gpkg_layer:
            # Layer was skipped (e.g., web layer already exists)
            results.skips.append(
                Issue(layer_name, "Layer already exists → not added back to project.")
            )
            continue

        if not gpkg_layer.isValid():
            msg = f"GeoPackage → Layer '{layer_name}' not found in GeoPackage."
            if uri:
                msg += f"\nlooked for: {uri}"
            log_debug(msg, Qgis.Warning)
            results.errors.append(
                Issue(
                    layer_name,
                    "Failed to add layer to project: Layer not found in GeoPackage.",
                )
            )
            continue

        project.addMapLayer(gpkg_layer, addToLegend=False)
        root.insertLayer(0, gpkg_layer)
        results.successes.append(layer_name)

        # Cloned web layers already have their style.
        if "url=" not in layer_to_find.source():
            copy_layer_style(layer_to_find, gpkg_layer)

    if results.successes:
        log_debug(
            f"GeoPackage → Added '{len(results.successes)}' layer(s) "
            "from the GeoPackage to the project.",
            Qgis.Success,
        )
    if results.errors:
        log_debug(
            f"GeoPackage → Could not find {len(results.errors)} layer(s) "
            "in GeoPackage.",
            Qgis.Warning,
        )

    return results


def copy_layers_to_gpkg() -> ActionResults[None]:
    """Copy the selected layers to the project's GeoPackage.

    Returns:
        ActionResults: An object containing the results of the operation.
    """
    added: ActionResults[dict[QgsMapLayer, str]] = add_layers_to_gpkg()

    # Only try to add back layers that were successfully processed
    # (or valid skips like web layers)
    layers_to_add_back: list[QgsMapLayer] = list(added.result.keys())

    back: ActionResults[None] = add_layers_from_gpkg_to_project(
        layers=layers_to_add_back, layer_mapping=added.result
    )

    return ActionResults(
        result=None,
        processed=added.processed,
        successes=back.successes,
        skips=added.skips + back.skips,
        errors=added.errors + back.errors,
    )
