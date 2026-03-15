"""Module: print_layout.py

This module contains functions for creating print layouts from templates.
"""

from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsExpressionContextUtils,
    QgsLayoutItem,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsLayoutManager,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsPathResolver,
    QgsPrintLayout,
    QgsProject,
    QgsReadWriteContext,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtXml import QDomDocument

from .constants import PAPER_SIZES, PaperProps
from .context import PluginContext
from .logs_and_errors import log_debug, raise_runtime_error

if TYPE_CHECKING:
    from pathlib import Path

    from qgis._gui import QgisInterface
    from qgis.gui import QgsMapCanvas


def _get_unique_layout_name(
    layout_manager: QgsLayoutManager, paper_size_name: str
) -> str:
    """Determine a unique name for the layout.

    Args:
        layout_manager: The project's layout manager.
        paper_size_name: The name of the paper size.

    Returns:
        A unique name for the new layout.
    """
    base_name: str = f"Layout {paper_size_name}"
    final_name: str = base_name
    counter: int = 1
    while layout_manager.layoutByName(final_name):
        final_name = f"{base_name} ({counter})"
        counter += 1
    return final_name


def _create_and_initialize_layout(project: QgsProject, name: str) -> QgsPrintLayout:
    """Create and initialize a new print layout.

    Args:
        project: The current QGIS project.
        name: The name for the new layout.

    Returns:
        The newly created and initialized layout.
    """
    layout = QgsPrintLayout(project)
    layout.setName(name)
    layout.initializeDefaults()
    return layout


def _set_layout_page_size(layout: QgsPrintLayout, paper_size_name: str) -> PaperProps:
    """Set the page size of the layout.

    Args:
        layout: The layout to modify.
        paper_size_name: The name of the paper size.

    Returns:
        The PaperProps object for the given paper size.
    """
    if not hasattr(PAPER_SIZES, paper_size_name):
        raise_runtime_error(f"Unknown paper size: {paper_size_name}")

    paper_props: PaperProps = getattr(PAPER_SIZES, paper_size_name)

    page_size_obj = QgsLayoutSize(
        paper_props.width, paper_props.height, QgsUnitTypes.LayoutMillimeters
    )

    if (page_collection := layout.pageCollection()) is None:
        raise_runtime_error("Layout has no page collection")
    if page_collection.pageCount() > 0:
        page = page_collection.pages()[0]
        page.setPageSize(page_size_obj)

    return paper_props


def _add_map_to_layout(layout: QgsPrintLayout, paper_props: PaperProps) -> None:
    """Add a map item to the layout, fitting the current view.

    The map item is sized to the full page, set to the current canvas extent,
    and placed at the bottom of the item stack.

    Args:
        layout: The layout to add the map to.
        paper_props: The properties of the paper, used for sizing the map.
    """
    iface: QgisInterface = PluginContext.iface()
    canvas: QgsMapCanvas | None = iface.mapCanvas()
    if not canvas:
        log_debug("No map canvas found. Layout created without map.", Qgis.Warning)
        return

    map_item = QgsLayoutItemMap(layout)
    # Disable the map's own frame, as we have a separate SVG frame
    map_item.setFrameEnabled(False)

    # Set map size to full page
    map_item.attemptSetSceneRect(QRectF(0, 0, paper_props.width, paper_props.height))

    # Set map extent to current view
    map_item.setExtent(canvas.extent())

    layout.addLayoutItem(map_item)

    # Move map to the bottom of the stacking order
    layout.moveItemToBottom(map_item)


def _add_frame_to_layout(layout: QgsPrintLayout, paper_props: PaperProps) -> None:
    """Add a frame from an SVG file to the layout.

    Args:
        layout: The layout to add the frame to.
        paper_props: The properties of the paper, including the frame path.
    """
    frame_svg_path: Path = paper_props.frame
    if not frame_svg_path.exists():
        log_debug(
            f"Frame SVG not found: {frame_svg_path}. Layout created without frame.",
            Qgis.Warning,
        )
        return

    frame_item = QgsLayoutItemPicture(layout)
    frame_item.setPicturePath(str(frame_svg_path))
    frame_item.attemptSetSceneRect(QRectF(0, 0, paper_props.width, paper_props.height))
    layout.addLayoutItem(frame_item)
    frame_item.setLocked(True)


def _load_template_document() -> QDomDocument:
    """Load the title block template XML document.

    Returns:
        QDomDocument: The loaded QDomDocument.

    Raises:
        RuntimeError: If the template file is not found, cannot be read,
            or is not valid XML.
    """
    template_path: Path = (
        PluginContext.templates_path() / "print_layout" / "title_block.qpt"
    )
    if not template_path.exists():
        raise_runtime_error(f"Template not found at: {template_path}")

    doc = QDomDocument()
    try:
        with template_path.open(encoding="utf-8") as f:
            content: str = f.read()
    except OSError as e:
        raise_runtime_error(f"Could not read template file: {e}")

    success, error_str, _, _ = doc.setContent(content)
    if not success:
        raise_runtime_error(f"Failed to parse title block template XML: {error_str}")
    return doc


def _move_title_block_to_corner(
    new_items: list[QgsLayoutItem], page_width: float, page_height: float
) -> None:
    """Move the newly added title block items to the bottom-right corner.

    Args:
        new_items: The list of new items added from the template.
        page_width: The width of the page.
        page_height: The height of the page.
    """
    margin_mm: float = 5.0

    # Calculate bounding box of the added template items
    bbox = new_items[0].sceneBoundingRect()
    for item in new_items[1:]:
        bbox = bbox.united(item.sceneBoundingRect())

    # Current bottom-right of the title block group
    current_max_x: float = bbox.right()
    current_max_y: float = bbox.bottom()

    # Target bottom-right
    target_max_x: float = page_width - margin_mm
    target_max_y: float = page_height - margin_mm

    shift_x: float = target_max_x - current_max_x
    shift_y: float = target_max_y - current_max_y

    # Move all new items
    for item in new_items:
        # Use item.pos() (QPointF in scene coords/mm) instead of item.position()
        # to ensures we don't mix units (e.g. adding mm shift to an item in inches).
        current_scene_pos = item.pos()
        new_pos = QgsLayoutPoint(
            current_scene_pos.x() + shift_x,
            current_scene_pos.y() + shift_y,
            QgsUnitTypes.LayoutMillimeters,
        )
        item.attemptMove(new_pos)


def create_print_layout(paper_size_name: str) -> None:
    """Create a new print layout with a specific paper size and title block.

    Args:
        paper_size_name: The name of the paper size (e.g., "A3", "A4").
    """
    project: QgsProject = PluginContext.project()
    layout_manager: QgsLayoutManager | None = project.layoutManager()
    if not layout_manager:
        raise_runtime_error("Project has no layout manager")

    # 1. Determine a unique name and create the layout
    final_name: str = _get_unique_layout_name(layout_manager, paper_size_name)
    layout: QgsPrintLayout = _create_and_initialize_layout(project, final_name)

    # 2. Set page size
    paper_props: PaperProps = _set_layout_page_size(layout, paper_size_name)

    # 3. Add map item showing the current view
    _add_map_to_layout(layout, paper_props)

    # 4. Add Frame from SVG
    _add_frame_to_layout(layout, paper_props)

    # 5. Load and add Title Block from Template
    doc: QDomDocument = _load_template_document()

    # Configure context to resolve relative paths (e.g. images)
    # against the template file location
    template_path: Path = (
        PluginContext.templates_path() / "print_layout" / "title_block.qpt"
    )
    rw_context = QgsReadWriteContext()
    rw_context.setPathResolver(QgsPathResolver(str(template_path)))

    if new_items := layout.addItemsFromXml(
        doc.documentElement(), doc, rw_context, pasteInPlace=False
    ):
        _move_title_block_to_corner(new_items, paper_props.width, paper_props.height)

    # 6. Set Dynamic Variables (Layout Variables)
    QgsExpressionContextUtils.setLayoutVariable(
        layout, "utec_paper_size", paper_props.name
    )

    # 7. Add layout to project and open it
    layout_manager.addLayout(layout)
    iface: QgisInterface = PluginContext.iface()
    iface.openLayoutDesigner(layout)

    log_debug(f"Created layout '{final_name}' with size {paper_size_name}")
