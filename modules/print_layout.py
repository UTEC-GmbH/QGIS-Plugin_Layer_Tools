"""Module: print_layout.py

This module contains functions for creating print layouts from templates.
"""

from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsExpressionContextUtils,
    QgsLayoutItem,
    QgsLayoutItemLabel,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsLayoutManager,
    QgsLayoutObject,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsPathResolver,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
    QgsReadWriteContext,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QRectF
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLineEdit,
    QTextEdit,
)
from qgis.PyQt.QtXml import QDomDocument

from .constants import MAP_SCALES, PAPER_SIZES, PaperProps
from .context import PluginContext
from .general import enforce_text_edit_limits
from .logs_and_errors import log_debug, raise_runtime_error
from .project_variables import (
    ProjectVariable,
    get_current_variable_value,
    get_project_variables,
)

if TYPE_CHECKING:
    from pathlib import Path

    from qgis.core import QgsLayoutItemPage
    from qgis.gui import QgisInterface, QgsMapCanvas


def _get_unique_layout_name(layout_manager: QgsLayoutManager) -> str:
    """Determine a unique name for the layout.

    Args:
        layout_manager: The project's layout manager.

    Returns:
        A unique name for the new layout.
    """

    layout_name: str = QCoreApplication.translate("PrintLayout", "Overview")
    counter: int = 1
    while layout_manager.layoutByName(layout_name):
        layout_name = f"{layout_name} ({counter})"
        counter += 1
    return layout_name


class NewLayoutDialog(QDialog):
    """Dialog for naming a new layout and editing project variables."""

    def __init__(self, project: QgsProject, suggested_name: str) -> None:
        """Initialize the dialog.

        Args:
            project: The current QGIS project.
            suggested_name: The default name suggested for the layout.
        """
        super().__init__(PluginContext.iface().mainWindow())
        self.project: QgsProject = project
        self.setWindowTitle(
            QCoreApplication.translate("PrintLayout", "Create Print Layout")
        )
        self.setMinimumWidth(450)

        self.form_layout: QFormLayout = QFormLayout(self)
        self.variable_edits: dict[str, QLineEdit | QTextEdit] = {}
        self.variables: list[ProjectVariable] = get_project_variables()

        # 1. Layout Name
        self.name_edit = QLineEdit(suggested_name)
        self.name_edit.setMaxLength(30)
        name_label: str = QCoreApplication.translate("PrintLayout", "Drawing Type")
        self.form_layout.addRow(name_label, self.name_edit)

        # Visual Separator
        separator: QFrame = QFrame()
        separator.setFixedHeight(15)
        self.form_layout.addRow(separator)

        # 2. Project Variables (Metadata)
        for variable in self.variables:
            edit: QLineEdit | QTextEdit
            current_value: str = get_current_variable_value(self.project, variable)

            if variable.is_multi_line:
                edit = QTextEdit()
                edit.setAcceptRichText(False)
                edit.setTabChangesFocus(True)
                edit.setPlainText(current_value)
                edit.setMaximumHeight(50)
                if (max_lines := variable.max_lines) is not None and (
                    max_chars := variable.max_chars_per_line
                ) is not None:
                    edit.textChanged.connect(
                        lambda widget=edit, lines=max_lines, chars=max_chars: (
                            enforce_text_edit_limits(widget, lines, chars)
                        )
                    )
            else:
                edit = QLineEdit()
                edit.setText(current_value)
                if variable.max_chars_per_line:
                    edit.setMaxLength(variable.max_chars_per_line)

            self.variable_edits[variable.id] = edit
            self.form_layout.addRow(variable.label, edit)

        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.form_layout.addRow(self.button_box)

    def get_layout_name(self) -> str:
        """Return the entered layout name."""
        return self.name_edit.text().strip()

    def save_variables(self) -> None:
        """Save entered project variables to the project."""
        for variable in self.variables:
            widget: QLineEdit | QTextEdit = self.variable_edits[variable.id]
            value: str = (
                widget.text().strip()
                if isinstance(widget, QLineEdit)
                else widget.toPlainText().strip()
            )

            QgsExpressionContextUtils.setProjectVariable(
                self.project, variable.name, value
            )
        log_debug("Project variables updated.", prefix="Project Properties → ")


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

    Raises:
        RuntimeError: If the paper size is unknown or the layout has no page
            collection.
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
        page: QgsLayoutItemPage = page_collection.pages()[0]
        page.setPageSize(page_size_obj)

    return paper_props


def _add_map_to_layout(
    layout: QgsPrintLayout, paper_props: PaperProps
) -> QgsLayoutItemMap | None:
    """Add a map item to the layout, fitting the current view.

    The map item is sized to the full page, set to the current canvas extent,
    and placed at the bottom of the item stack.

    Args:
        layout: The layout to add the map to.
        paper_props: The properties of the paper, used for sizing the map.

    Returns:
        The created map item, or None if no map canvas was available.
    """
    iface: QgisInterface = PluginContext.iface()
    canvas: QgsMapCanvas | None = iface.mapCanvas()
    if not canvas:
        log_debug("No map canvas found. Layout created without map.", Qgis.Warning)
        return None

    map_item = QgsLayoutItemMap(layout)

    # Disable the map's own frame, as we have a separate SVG frame
    map_item.setFrameEnabled(False)

    # Set map size to full page
    map_item.setId("Karte_1")
    map_item.attemptSetSceneRect(QRectF(0, 0, paper_props.width, paper_props.height))

    # Zoom to the current canvas extent (centers content and fits it)
    map_item.zoomToExtent(canvas.extent())

    # Calculate target scale based on current canvas scale
    current_scale: float = canvas.scale()
    target_scale: float = next(
        (scale for scale in MAP_SCALES if scale >= current_scale),
        current_scale,
    )
    map_item.setScale(target_scale)

    # Check if a map theme exists with the same name as the layout.
    layout_name: str = layout.name()
    if (
        (project := layout.project())
        and (theme_collection := project.mapThemeCollection())
        and layout_name in theme_collection.mapThemes()
    ):
        map_item.setFollowVisibilityPresetName(layout_name)
        map_item.setFollowVisibilityPreset(True)

    layout.addLayoutItem(map_item)

    # Move map to the bottom of the stacking order
    layout.moveItemToBottom(map_item)

    return map_item


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
    frame_item.setId(QCoreApplication.translate("PrintLayout", "Frame"))
    frame_item.setPicturePath(str(frame_svg_path))
    frame_item.attemptSetSceneRect(QRectF(0, 0, paper_props.width, paper_props.height))
    layout.addLayoutItem(frame_item)
    frame_item.setLocked(True)


def _auto_dynamic_elements(
    new_items: list[QgsLayoutItem], map_item: QgsLayoutItemMap
) -> None:
    """Link items from the template to the main map.

    This function finds specific items like a north arrow or a scale label
    by their ID and links them to the provided map item. To make items
    findable, set their "Item ID" in the QGIS Layout item properties.
    For this function, the following IDs are used:
    - "Nordpfeil": for a QgsLayoutItemPicture to be used as a north arrow.
    - "Maßstab": for a QgsLayoutItemLabel that should display the map scale.

    Args:
        new_items: A list of items loaded from the template.
        map_item: The main map item in the layout.
    """
    map_id: str = map_item.id()
    if not map_id:
        log_debug("Main map has no ID, cannot link template items.", Qgis.Warning)
        return

    for item in new_items:
        item_id: str = item.id()
        if not item_id:
            continue

        # Link north arrow
        if item_id == "Nordpfeil" and isinstance(item, QgsLayoutItemPicture):
            item.setLinkedMap(map_item)
            item.setPictureRotation(0)
            item.setReferencePoint(QgsLayoutItem.ReferencePoint.Middle)
            item.dataDefinedProperties().setProperty(
                QgsLayoutObject.ItemRotation,
                QgsProperty.fromExpression(
                    f"map_get(item_variables('{map_id}'), 'map_rotation')"
                ),
            )

        # Link scale label
        elif item_id == "Maßstab" and isinstance(item, QgsLayoutItemLabel):
            log_debug(f"Linking scale label to map '{map_id}'")
            expression: str = (
                f"'1:' || format_number(round(map_get(item_variables('{map_id}'), "
                "'map_scale')), 0)"
            )
            item.setText(f"[% {expression} %]")
            item.refresh()


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

    content_result = doc.setContent(content)
    if not content_result[0]:
        error_str: str = content_result[1]
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

    top_level_items: list[QgsLayoutItem] = [
        item
        for item in new_items
        if not (item.parentGroup() and item.parentGroup() in new_items)
    ]

    if not top_level_items:
        return

    # Calculate bounding box of the added template items
    bbox = top_level_items[0].sceneBoundingRect()
    for item in top_level_items[1:]:
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
    for item in top_level_items:
        current_scene_pos = item.pos()
        new_pos = QgsLayoutPoint(
            current_scene_pos.x() + shift_x,
            current_scene_pos.y() + shift_y,
            QgsUnitTypes.LayoutMillimeters,
        )
        item.attemptMove(new_pos)


def create_print_layout(paper_size_name: str) -> None:
    """Create a new print layout with a specific paper size and title block.

    This function orchestrates the creation of a complete print layout. It:
    1. Creates a new layout with a unique name.
    2. Sets the specified paper size.
    3. Adds a map item reflecting the current canvas view.
    4. Adds a decorative frame from an SVG file.
    5. Loads and adds a title block from a .qpt template.
    6. Sets layout-specific variables.
    7. Adds the new layout to the project and opens it in the layout designer.

    Args:
        paper_size_name: The name of the paper size (e.g., "a4_landscape").

    Raises:
        RuntimeError: If the project has no layout manager, or if a required
            template file is missing or invalid.
    """
    project: QgsProject = PluginContext.project()
    if (layout_manager := project.layoutManager()) is None:
        raise_runtime_error("Project has no layout manager")

    # 1. Determine a unique name and create the layout
    suggested_name: str = _get_unique_layout_name(layout_manager)

    dialog = NewLayoutDialog(project, suggested_name)
    if not dialog.exec_():
        log_debug("Layout creation cancelled by user.", Qgis.Info)
        return

    final_name: str = dialog.get_layout_name() or suggested_name
    dialog.save_variables()
    project.setDirty(True)

    layout: QgsPrintLayout = _create_and_initialize_layout(project, final_name)

    # 2. Set page size
    paper_props: PaperProps = _set_layout_page_size(layout, paper_size_name)

    # 3. Add map item showing the current view
    map_item: QgsLayoutItemMap | None = _add_map_to_layout(layout, paper_props)

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
        if map_item:
            _auto_dynamic_elements(new_items, map_item)
        _move_title_block_to_corner(new_items, paper_props.width, paper_props.height)

    # 6. Set Dynamic Variables (Layout Variables)
    QgsExpressionContextUtils.setLayoutVariable(
        layout, "utec_paper_size", paper_props.name.split(" ")[0]
    )

    # 7. Add layout to project and open it
    layout_manager.addLayout(layout)
    iface: QgisInterface = PluginContext.iface()
    iface.openLayoutDesigner(layout)

    log_debug(f"Created layout '{final_name}' with size {paper_size_name}")
