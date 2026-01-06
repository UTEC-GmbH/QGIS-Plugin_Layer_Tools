"""Module: shipping.py

This module contains functions for preparing selected layers for sending to clients.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsLayout,
    QgsMapThemeCollection,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
)
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtXml import QDomDocument

from .context import PluginContext
from .general import get_selected_layers
from .geopackage import add_layers_from_gpkg_to_project, add_layers_to_gpkg, create_gpkg
from .logs_and_errors import log_debug

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from qgis.core import QgsLayoutManager, QgsMapLayer
    from qgis.gui import QgisInterface


def _copy_layouts(source_project: QgsProject, target_project: QgsProject) -> None:
    """Copy all layouts from a source project to a target project.

    Args:
        source_project: The project to copy layouts from.
        target_project: The project to copy layouts to.
    """
    source_layout_manager: QgsLayoutManager | None = source_project.layoutManager()
    target_layout_manager: QgsLayoutManager | None = target_project.layoutManager()

    # Remove default layout that might be created with a new project
    if target_layout_manager and source_layout_manager:
        for layout in target_layout_manager.layouts():
            target_layout_manager.removeLayout(layout)

        layouts: Iterable[QgsLayout] = source_layout_manager.layouts()
        for layout in layouts:
            if isinstance(layout, QgsPrintLayout):
                # Clone the layout to avoid modifying the original
                new_layout: QgsPrintLayout = layout.clone()
                target_layout_manager.addLayout(new_layout)


def _copy_project_properties(
    source_project: QgsProject, target_project: QgsProject
) -> None:
    """Copy key properties from a source project to a target project.

    This includes CRS, title, map themes, layouts, and the initial map extent.

    Args:
        source_project: The project to copy properties from.
        target_project: The project to copy properties to.
    """
    # 1. Copy Coordinate Reference System (CRS)
    target_project.setCrs(source_project.crs())

    # 2. Copy Project Title
    target_project.setTitle(source_project.title())

    # 3. Copy Map Themes (Layer visibility presets)
    source_mtc: QgsMapThemeCollection | None = source_project.mapThemeCollection()
    target_mtc: QgsMapThemeCollection = target_project.mapThemeCollection()
    if source_mtc and target_mtc:
        doc = QDomDocument()
        doc.appendChild(doc.createElement("qgis"))
        source_mtc.writeXml(doc)
        target_mtc.readXml(doc)

    # 4. Copy Layouts (Print Composer)
    _copy_layouts(source_project, target_project)


def _set_map_extent(source_canvas: QgsMapCanvas, target_project: QgsProject) -> None:
    """Copy the current map extent (zoom and position) to the new project file.

    Args:
        source_canvas: The source project's map canvas.
        target_project: The target project where the extent will be applied.
    """
    source_extent: QgsRectangle = source_canvas.extent()
    source_crs: QgsCoordinateReferenceSystem = (
        source_canvas.mapSettings().destinationCrs()
    )
    source_view = QgsReferencedRectangle(source_extent, source_crs)

    if target_view_settings := target_project.viewSettings():
        target_view_settings.setDefaultViewExtent(source_view)
    else:
        log_debug(
            "Shipping → Target project view settings could not be accessed",
            Qgis.Warning,
        )


def prepare_layers_for_shipping() -> None:
    """Prepare selected layers for shipping.

    Creates a 'Versand' folder in the project directory, generates a GeoPackage
    containing the selected layers, and creates a companion .qgz project file
    with the same styling and layout properties.
    """
    # Get current project and interface to copy properties from
    original_project: QgsProject = PluginContext.project()

    layers: list[QgsMapLayer] = get_selected_layers()

    project_path: Path = PluginContext.project_path()
    versand_dir: Path = project_path.parent / "Versand"
    versand_dir.mkdir(exist_ok=True)

    # Use local time for the filename
    date_str: str = datetime.now().astimezone().strftime("%Y_%m_%d")
    base_name: str = f"{project_path.stem}_{date_str}"

    # Create a GeoPackage and add the layers to it
    gpkg_path: Path = create_gpkg(
        versand_dir / f"{base_name}.gpkg", delete_existing=True
    )
    results: dict = add_layers_to_gpkg(layers=layers, gpkg_path=gpkg_path)

    if not results["successes"]:
        return

    # Create Shipping Project file
    qgz_path: Path = versand_dir / f"{base_name}.qgz"
    shipping_project = QgsProject()
    shipping_project.setFileName(str(qgz_path))
    _copy_project_properties(original_project, shipping_project)

    add_layers_from_gpkg_to_project(
        gpkg_path=gpkg_path,
        project=shipping_project,
        layers=list(reversed(layers)),
        layer_mapping=results["layer_mapping"],
    )

    # Set initial map extent to the current view of the original project
    iface: QgisInterface | None = PluginContext.iface()
    if iface and (current_canvas := iface.mapCanvas()):
        _set_map_extent(current_canvas, shipping_project)

    # Save the shipping project
    shipping_project.write()
    log_debug(f"Created shipping project: {qgz_path}", Qgis.Success)
