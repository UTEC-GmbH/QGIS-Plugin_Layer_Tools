"""Module: print_layout.py

This module contains functions for creating print layouts from templates.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsExpressionContextUtils,
    QgsLayoutItem,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsLayoutManager,
    QgsLayoutObject,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendStyle,
    QgsPathResolver,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
    QgsReadWriteContext,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QRectF
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QWidget,
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


@dataclass
class LayoutMetadata:
    """Container for dynamic values applied to layout items."""

    source_visible: bool
    source_text: str
    drafter: str
    drafter_date: str
    checker: str
    checker_date: str


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

        self._setup_layout_inputs(suggested_name)
        self._setup_source_inputs()
        self._setup_variable_inputs()
        self._setup_dialog_buttons()

    def _setup_layout_inputs(self, suggested_name: str) -> None:
        """Set up inputs for layout name, paper, and drafter/checker metadata.

        Args:
            suggested_name: The default name suggested for the layout.
        """
        self.name_edit = self._add_labeled_line_edit(
            suggested_name,
            30,
            QCoreApplication.translate("PrintLayout", "Drawing Type"),
        )

        separator: QFrame = QFrame()
        separator.setFixedHeight(15)
        self.form_layout.addRow(separator)

        available_sizes: set[str] = {
            paper_props.size_name.split("_")[0] for paper_props in PAPER_SIZES
        }
        self.paper_size_combo = QComboBox()
        for size in sorted(available_sizes, key=lambda value: int(value[1:])):
            self.paper_size_combo.addItem(size.upper(), size)

        available_orientations: set[str] = {
            paper_props.size_name.split("_")[1] for paper_props in PAPER_SIZES
        }
        orientation_labels: dict[str, str] = {
            "landscape": QCoreApplication.translate("PrintLayout", "Landscape"),
            "portrait": QCoreApplication.translate("PrintLayout", "Portrait"),
        }
        self.paper_orientation_combo = QComboBox()
        for orientation in ("landscape", "portrait"):
            if orientation in available_orientations:
                self.paper_orientation_combo.addItem(
                    orientation_labels[orientation],
                    orientation,
                )

        paper_options_widget = QWidget()
        paper_options_layout = QHBoxLayout(paper_options_widget)
        paper_options_layout.setContentsMargins(0, 0, 0, 0)

        paper_options_layout.addWidget(self.paper_size_combo)

        paper_options_layout.addWidget(self.paper_orientation_combo)

        paper_format_label = QLabel(
            QCoreApplication.translate("PrintLayout", "Paper Format")
        )
        paper_format_label.setBuddy(self.paper_size_combo)
        self.form_layout.addRow(paper_format_label, paper_options_widget)

        default_size_index: int = self.paper_size_combo.findData("a3")
        default_orientation_index: int = self.paper_orientation_combo.findData(
            "landscape"
        )
        if default_size_index < 0 or default_orientation_index < 0:
            raise_runtime_error("A3 Landscape is not available as a paper size")
        self.paper_size_combo.setCurrentIndex(default_size_index)
        self.paper_orientation_combo.setCurrentIndex(default_orientation_index)

        separator_end: QFrame = QFrame()
        separator_end.setFixedHeight(15)
        self.form_layout.addRow(separator_end)

    def _add_labeled_line_edit(
        self, default_value: str, max_length: int, label_text: str
    ) -> QLineEdit:
        """Create a QLineEdit with a label and add it to the form layout.

        Args:
            default_value: The initial text for the input box.
            max_length: The maximum number of characters allowed.
            label_text: The untranslated label text for the form row.

        Returns:
            QLineEdit: The created line edit widget.
        """
        line_edit = QLineEdit(default_value)
        line_edit.setMaxLength(max_length)
        self.form_layout.addRow(label_text, line_edit)

        return line_edit

    def _setup_source_inputs(self) -> None:
        """Set up inputs for the background map source."""

        self.legend_checkbox = QCheckBox()
        self.legend_checkbox.setChecked(True)
        self.form_layout.addRow(
            QCoreApplication.translate("PrintLayout", "Legend"),
            self.legend_checkbox,
        )

        self.source_checkbox = QCheckBox()
        self.source_checkbox.setChecked(False)

        self.source_edit = QLineEdit(
            QCoreApplication.translate(
                "PrintLayout", "Source of Background Maps: LGLN Niedersachsen"
            )
        )
        self.source_edit.setEnabled(False)
        self.source_checkbox.toggled.connect(self.source_edit.setEnabled)

        source_options_widget = QWidget()
        source_options_layout = QHBoxLayout(source_options_widget)
        source_options_layout.setContentsMargins(0, 0, 0, 0)
        source_options_layout.addWidget(self.source_checkbox)
        source_options_layout.addWidget(self.source_edit, 1)
        self.form_layout.addRow(
            QCoreApplication.translate("PrintLayout", "Source"),
            source_options_widget,
        )

        separator_end: QFrame = QFrame()
        separator_end.setFixedHeight(15)
        self.form_layout.addRow(separator_end)

    def _setup_variable_inputs(self) -> None:
        """Add inputs for project-specific metadata variables."""

        for variable in self.variables:
            edit: QLineEdit | QTextEdit = self._create_variable_widget(variable)
            self.variable_edits[variable.id] = edit
            self.form_layout.addRow(variable.label, edit)

        separator: QFrame = QFrame()
        separator.setFixedHeight(15)
        self.form_layout.addRow(separator)

        self.drafter_edit, self.drafter_date_edit = self._add_person_inputs(
            "XY",
            datetime.now().astimezone().strftime("%d.%m.%Y"),
            QCoreApplication.translate("PrintLayout", "Drafter"),
        )
        self.checker_edit, self.checker_date_edit = self._add_person_inputs(
            "",
            "",
            QCoreApplication.translate("PrintLayout", "Checker"),
        )

        separator_end: QFrame = QFrame()
        separator_end.setFixedHeight(15)
        self.form_layout.addRow(separator_end)

    def _add_person_inputs(
        self, initials: str, date: str, label_text: str
    ) -> tuple[QLineEdit, QLineEdit]:
        """Add a row with initials and date inputs for a drawing role.

        Args:
            initials: The initial text for the initials input.
            date: The initial text for the date input.
            label_text: The text displayed for this drawing role.

        Returns:
            The initials and date input widgets.
        """
        initials_edit = QLineEdit(initials)
        initials_edit.setMaxLength(6)

        date_edit = QLineEdit(date)
        date_edit.setMaxLength(10)

        inputs_widget = QWidget()
        inputs_layout = QHBoxLayout(inputs_widget)
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        inputs_layout.addWidget(initials_edit)
        inputs_layout.addWidget(date_edit)

        label = QLabel(label_text)
        label.setBuddy(initials_edit)
        self.form_layout.addRow(label, inputs_widget)

        return initials_edit, date_edit

    def _create_variable_widget(
        self, variable: ProjectVariable
    ) -> QLineEdit | QTextEdit:
        """Create the appropriate widget for a project variable.

        Args:
            variable: The project variable definition.

        Returns:
            QLineEdit | QTextEdit: The created input widget.
        """
        current_value: str = get_current_variable_value(self.project, variable)

        if not variable.is_multi_line:
            edit = QLineEdit(current_value)
            if variable.max_chars_per_line:
                edit.setMaxLength(variable.max_chars_per_line)
            return edit

        text_edit = QTextEdit()
        text_edit.setAcceptRichText(False)
        text_edit.setTabChangesFocus(True)
        text_edit.setPlainText(current_value)
        text_edit.setMaximumHeight(50)

        if (max_lines := variable.max_lines) is not None and (
            max_chars := variable.max_chars_per_line
        ) is not None:
            text_edit.textChanged.connect(
                lambda widget=text_edit, lines=max_lines, chars=max_chars: (
                    enforce_text_edit_limits(widget, lines, chars)
                )
            )

        return text_edit

    def _setup_dialog_buttons(self) -> None:
        """Add standard Ok/Cancel buttons to the dialog."""
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.form_layout.addRow(self.button_box)

    def get_layout_name(self) -> str:
        """Return the entered layout name."""
        return self.name_edit.text().strip()

    def get_paper_size_name(self) -> str:
        """Return the selected paper size and orientation identifier."""
        paper_size = self.paper_size_combo.currentData()
        orientation = self.paper_orientation_combo.currentData()
        if not isinstance(paper_size, str) or not isinstance(orientation, str):
            raise_runtime_error("Paper size and orientation must be selected")
        paper_size_name = f"{paper_size}_{orientation}"
        if not hasattr(PAPER_SIZES, paper_size_name):
            raise_runtime_error(f"Unknown paper size: {paper_size_name}")
        return paper_size_name

    def get_source_visibility(self) -> bool:
        """Return True if the source should be visible."""
        return self.source_checkbox.isChecked()

    def get_source_text(self) -> str:
        """Return the source text."""
        return self.source_edit.text().strip()

    def get_add_legend(self) -> bool:
        """Return True if a legend should be added to the layout."""
        return self.legend_checkbox.isChecked()

    def get_drafter_initials(self) -> str:
        """Return the entered drafter initials."""
        return self.drafter_edit.text().strip().upper()

    def get_checker_initials(self) -> str:
        """Return the entered checker initials."""
        return self.checker_edit.text().strip().upper()

    def get_drafter_date(self) -> str:
        """Return the entered drafter date."""
        return self.drafter_date_edit.text().strip()

    def get_checker_date(self) -> str:
        """Return the entered checker date."""
        return self.checker_date_edit.text().strip()

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
    new_items: list[QgsLayoutItem],
    map_item: QgsLayoutItemMap | None,
    metadata: LayoutMetadata,
) -> None:
    """Link items from the template to the main map and update the source text.

    This function finds specific items like a north arrow or a scale label by their ID
    and links them to the provided map item. It also handles the visibility and content
    of the "Quelle" text object.

    To make items findable, set their "Item ID" in the QGIS Layout item properties.
    For this function, the following IDs are used:
    - "Nordpfeil": for a QgsLayoutItemPicture to be used as a north arrow.
    - "Maßstab": for a QgsLayoutItemLabel that should display the map scale.
    - "Quelle": for a QgsLayoutItemLabel that should display the map source.
    - "gezeichnet - Name": for a QgsLayoutItemLabel for the drafter initials.
    - "gezeichnet - Datum": for a QgsLayoutItemLabel for the drafter date.
    - "geprüft - Name": for a QgsLayoutItemLabel for the checker initials.
    - "geprüft - Datum": for a QgsLayoutItemLabel for the check date.

    Args:
        new_items: A list of items loaded from the template.
        map_item: The main map item in the layout, or None.
        metadata: The dynamic values to apply to the elements.
    """
    can_link_map: bool = bool(map_item and map_item.id())
    if map_item and not can_link_map:
        log_debug("Main map has no ID, cannot link template items.", Qgis.Warning)

    for item in new_items:
        if not (item_id := item.id()):
            continue

        if _handle_static_labels(
            item=item,
            item_id=item_id,
            metadata=metadata,
        ):
            continue

        if can_link_map and map_item:
            _handle_map_linked_items(item, item_id, map_item)


def _handle_static_labels(
    item: QgsLayoutItem,
    item_id: str,
    metadata: LayoutMetadata,
) -> bool:
    """Handle layout items that display static text or basic metadata.

    Args:
        item: The layout item to process.
        item_id: The ID of the item.
        metadata: The dynamic values to apply.

    Returns:
        bool: True if the item was handled by this function.
    """
    if item_id == "Quelle":
        item.setVisibility(metadata.source_visible)
        if isinstance(item, QgsLayoutItemLabel):
            item.setText(metadata.source_text)
            item.refresh()
        return True

    if not isinstance(item, QgsLayoutItemLabel):
        return False

    if item_id == "gezeichnet - Name":
        item.setText(metadata.drafter)
        item.refresh()
        return True

    if item_id == "geprüft - Name":
        item.setText(metadata.checker)
        item.refresh()
        return True

    if item_id == "gezeichnet - Datum":
        item.setText(metadata.drafter_date)
        item.refresh()
        return True

    if item_id == "geprüft - Datum":
        item.setText(metadata.checker_date)
        item.refresh()
        return True

    return False


def _handle_map_linked_items(
    item: QgsLayoutItem, item_id: str, map_item: QgsLayoutItemMap
) -> None:
    """Handle items that need to be synchronized with a specific map item.

    Args:
        item: The layout item to process.
        item_id: The ID of the item.
        map_item: The map item to link to.
    """
    map_id: str = map_item.id()

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


def _scale_title_block_template(doc: QDomDocument, scaling: float) -> None:
    """Scale the title block group and its contents in the template document."""
    if scaling <= 0:
        raise_runtime_error(f"Invalid title block scaling: {scaling}")
    if scaling == 1.0:
        return

    layout_items = doc.elementsByTagName("LayoutItem")
    group_element = next(
        (
            layout_items.at(index).toElement()
            for index in range(layout_items.count())
            if layout_items.at(index).toElement().attribute("id")
            == "Title_Block_Gruppe"
        ),
        None,
    )
    if group_element is None:
        raise_runtime_error("Title block group not found in template")

    group_uuid: str = group_element.attribute("uuid")
    if not group_uuid:
        raise_runtime_error("Title block group has no UUID in template")

    origin_x, origin_y, _ = group_element.attribute("position").split(",")
    origin_x = float(origin_x)
    origin_y = float(origin_y)

    for index in range(layout_items.count()):
        item_element = layout_items.at(index).toElement()
        if item_element == group_element:
            width, height, unit = item_element.attribute("size").split(",")
            item_element.setAttribute(
                "size",
                f"{float(width) * scaling},{float(height) * scaling},{unit}",
            )
        elif item_element.attribute("groupUuid") == group_uuid:
            for attribute in ("position", "positionOnPage"):
                if not item_element.hasAttribute(attribute):
                    continue
                x, y, unit = item_element.attribute(attribute).split(",")
                item_element.setAttribute(
                    attribute,
                    (
                        f"{origin_x + (float(x) - origin_x) * scaling},"
                        f"{origin_y + (float(y) - origin_y) * scaling},"
                        f"{unit}"
                    ),
                )

            width, height, unit = item_element.attribute("size").split(",")
            item_element.setAttribute(
                "size",
                f"{float(width) * scaling},{float(height) * scaling},{unit}",
            )

            text_styles = item_element.elementsByTagName("text-style")
            for style_index in range(text_styles.count()):
                style_element = text_styles.at(style_index).toElement()
                if style_element.hasAttribute("fontSize"):
                    font_size = float(style_element.attribute("fontSize"))
                    style_element.setAttribute("fontSize", str(font_size * scaling))


def _move_title_block_to_corner(
    new_items: list[QgsLayoutItem], page_width: float, page_height: float
) -> QRectF | None:
    """Move the newly added title block items to the bottom-right corner.

    Args:
        new_items: The list of new items added from the template.
        page_width: The width of the page.
        page_height: The height of the page.

    Returns:
        The bounding box of the moved title block, or None if it has no items.
    """
    margin_right_mm: float = 5.0
    margin_bottom_mm: float = 1.0

    top_level_items: list[QgsLayoutItem] = [
        item
        for item in new_items
        if not (item.parentGroup() and item.parentGroup() in new_items)
    ]

    if not top_level_items:
        return None

    # Calculate bounding box of the added template items
    bbox = top_level_items[0].sceneBoundingRect()
    for item in top_level_items[1:]:
        bbox = bbox.united(item.sceneBoundingRect())

    # Current bottom-right of the title block group
    current_max_x: float = bbox.right()
    current_max_y: float = bbox.bottom()

    # Target bottom-right
    target_max_x: float = page_width - margin_right_mm
    target_max_y: float = page_height - margin_bottom_mm

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

    return bbox.translated(shift_x, shift_y)


def _add_legend_to_layout(
    layout: QgsPrintLayout,
    map_item: QgsLayoutItemMap,
    title_block_bbox: QRectF,
    scaling: float = 1.0,
) -> None:
    """Add a framed, map-filtered, optionally scaled legend above the title block."""
    legend = QgsLayoutItemLegend(layout)
    legend.setTitle("Legende")
    legend.setLinkedMap(map_item)
    legend.setLegendFilterByMapEnabled(True)
    legend.setFrameEnabled(True)
    legend.setStyleMargin(QgsLegendStyle.Group, 6)
    legend.setStyleMargin(QgsLegendStyle.Group, QgsLegendStyle.Bottom, 1)

    title_style = legend.rstyle(QgsLegendStyle.Title)
    title_format = title_style.textFormat()
    title_font = title_format.font()
    title_font.setUnderline(True)
    title_format.setFont(title_font)
    title_style.setTextFormat(title_format)
    legend.setStyle(QgsLegendStyle.Title, title_style)

    if scaling <= 0:
        raise_runtime_error(f"Invalid legend scaling: {scaling}")
    legend.setScale(scaling)
    legend.setReferencePoint(QgsLayoutItem.ReferencePoint.LowerRight)
    layout.addLayoutItem(legend)
    legend.adjustBoxSize()
    legend.attemptMove(
        QgsLayoutPoint(
            title_block_bbox.right(),
            title_block_bbox.top(),
            QgsUnitTypes.LayoutMillimeters,
        )
    )


def create_print_layout() -> None:
    """Create a new print layout with the selected paper size and title block.

    This function orchestrates the creation of a complete print layout. It:
    1. Creates a new layout with a unique name.
    2. Sets the specified paper size.
    3. Adds a map item reflecting the current canvas view.
    4. Adds a decorative frame from an SVG file.
    5. Loads and adds a title block from a .qpt template.
    6. Optionally adds a legend linked to the main map.
    7. Sets layout-specific variables.
    8. Adds the new layout to the project and opens it in the layout designer.

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

    add_legend: bool = dialog.get_add_legend()
    paper_size_name: str = dialog.get_paper_size_name()

    # Package metadata into a dataclass to reduce argument counts
    metadata: LayoutMetadata = LayoutMetadata(
        source_visible=dialog.get_source_visibility(),
        source_text=dialog.get_source_text(),
        drafter=dialog.get_drafter_initials(),
        drafter_date=dialog.get_drafter_date(),
        checker=dialog.get_checker_initials(),
        checker_date=dialog.get_checker_date(),
    )

    final_name_entry: str = dialog.get_layout_name()
    final_name: str = final_name_entry or suggested_name

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
    _scale_title_block_template(doc, paper_props.title_block_scaling)

    # Configure context to resolve relative paths (e.g. images)
    # against the template file location
    template_path: Path = (
        PluginContext.templates_path() / "print_layout" / "title_block.qpt"
    )
    rw_context = QgsReadWriteContext()
    rw_context.setPathResolver(QgsPathResolver(str(template_path)))

    title_block_bbox: QRectF | None = None
    if new_items := layout.addItemsFromXml(
        doc.documentElement(), doc, rw_context, pasteInPlace=False
    ):
        _auto_dynamic_elements(new_items, map_item, metadata)
        title_block_bbox = _move_title_block_to_corner(
            new_items, paper_props.width, paper_props.height
        )

    if add_legend:
        if map_item and title_block_bbox:
            _add_legend_to_layout(
                layout,
                map_item,
                title_block_bbox,
                paper_props.title_block_scaling,
            )
        else:
            log_debug(
                "Cannot add legend without a main map and title block.",
                Qgis.Warning,
            )

    # 6. Set Dynamic Variables (Layout Variables)
    QgsExpressionContextUtils.setLayoutVariable(
        layout, "utec_paper_size", paper_props.name.split(" ")[0]
    )

    # 7. Add layout to project and open it
    layout_manager.addLayout(layout)
    iface: QgisInterface = PluginContext.iface()
    iface.openLayoutDesigner(layout)

    log_debug(f"Created layout '{final_name}' with size {paper_size_name}")
