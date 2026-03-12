"""Module: print_layout.py

This module contains functions for creating print layouts from templates.
"""

from qgis.core import (
    Qgis,
    QgsExpressionContextUtils,
    QgsLayoutItemPicture,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsPrintLayout,
    QgsProject,
    QgsReadWriteContext,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtXml import QDomDocument

from .constants import PAPER_SIZES
from .context import PluginContext
from .logs_and_errors import log_debug, raise_runtime_error


def create_print_layout(paper_size_name: str) -> None:
    """Create a new print layout with a specific paper size and title block.

    Args:
        paper_size_name: The name of the paper size (e.g., "A3", "A4").
    """
    project: QgsProject = PluginContext.project()
    layout_manager = project.layoutManager()

    # 1. Determine a unique name for the layout
    base_name = f"Layout {paper_size_name}"
    final_name = base_name
    counter = 1
    while layout_manager.layoutByName(final_name):
        final_name = f"{base_name} ({counter})"
        counter += 1

    # 2. Create and initialize the layout
    layout = QgsPrintLayout(project)
    layout.setName(final_name)
    layout.initializeDefaults()

    # 3. Set page size
    if not hasattr(PAPER_SIZES, paper_size_name):
        raise_runtime_error(f"Unknown paper size: {paper_size_name}")

    paper_props = getattr(PAPER_SIZES, paper_size_name)
    width = paper_props.width
    height = paper_props.height

    page_size_obj = QgsLayoutSize(width, height, QgsUnitTypes.LayoutMillimeters)

    # Assuming single page layout for simplicity
    page_collection = layout.pageCollection()
    if page_collection.pageCount() > 0:
        page = page_collection.pages()[0]
        page.setPageSize(page_size_obj)

    # 4. Add Frame from SVG
    frame_svg_path = paper_props.frame
    if not frame_svg_path.exists():
        log_debug(
            f"Frame SVG not found: {frame_svg_path}. Layout created without frame.",
            Qgis.Warning,
        )
    else:
        frame_item = QgsLayoutItemPicture(layout)
        frame_item.setPicturePath(str(frame_svg_path))
        # Assume the frame SVG is designed to fit the page exactly.
        frame_item.attemptSetSceneRect(QRectF(0, 0, width, height))
        layout.addLayoutItem(frame_item)
        # Lock the frame so it's not moved by accident
        frame_item.setLocked(True)

    # 5. Load Title Block Template
    template_path = PluginContext.templates_path() / "title_block.qpt"
    if not template_path.exists():
        raise_runtime_error(f"Template not found at: {template_path}")

    doc = QDomDocument()
    with open(template_path, encoding="utf-8") as f:
        content = f.read()
        if not doc.setContent(content):
            raise_runtime_error("Failed to parse title block template XML.")

    # Track items before adding template to identify the new ones
    items_before = set(layout.items())

    # Add items from template (false = don't use a new undo command group)
    layout.addItemsFromXml(doc.documentElement(), doc, QgsReadWriteContext(), False)

    if new_items := [item for item in layout.items() if item not in items_before]:
        # 6. Calculate position to move title block
        # We want 5mm from Right and 5mm from Bottom
        margin_mm = 5.0

        # Calculate bounding box of the added template items
        # Initialize with the first item's rect
        bbox = new_items[0].sceneBoundingRect()
        for item in new_items[1:]:
            bbox = bbox.united(item.sceneBoundingRect())

        # Current bottom-right of the title block group
        current_max_x = bbox.right()
        current_max_y = bbox.bottom()

        # Target bottom-right
        target_max_x = width - margin_mm
        target_max_y = height - margin_mm

        shift_x = target_max_x - current_max_x
        shift_y = target_max_y - current_max_y

        # Move all new items
        for item in new_items:
            # layout units are usually mm, but check item pos units to be safe
            # simplified: assuming items in template are set to mm
            current_pos = item.position()
            new_pos = QgsLayoutPoint(
                current_pos.x() + shift_x,
                current_pos.y() + shift_y,
                current_pos.units(),
            )
            item.attemptMove(new_pos)

    # 7. Set Dynamic Variables (Layout Variables)
    # The title block label in the template should use [% @utec_paper_size %]
    QgsExpressionContextUtils.setLayoutVariable(
        layout, "utec_paper_size", paper_props.name
    )

    # Add layout to project and open it
    layout_manager.addLayout(layout)
    iface = PluginContext.iface()
    iface.openLayoutDesigner(layout)

    log_debug(f"Created layout '{final_name}' with size {paper_size_name}")
