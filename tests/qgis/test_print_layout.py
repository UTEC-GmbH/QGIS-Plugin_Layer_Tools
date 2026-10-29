"""Tests for print layout creation options."""

from datetime import datetime

import pytest
from qgis.core import (
    QgsLayoutItem,
    QgsLayoutItemGroup,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLegendStyle,
    QgsPrintLayout,
    QgsReadWriteContext,
)
from qgis.PyQt.QtCore import QCoreApplication, QRectF

from modules.constants import PAPER_SIZES
from modules.print_layout import (
    LayoutMetadata,
    NewLayoutDialog,
    _add_legend_to_layout,
    _auto_dynamic_elements,
    _load_template_document,
    _move_title_block_to_corner,
    _scale_title_block_template,
)


def test_layout_options_use_separate_paper_size_and_orientation(clean_project) -> None:
    dialog = NewLayoutDialog(clean_project, "Test Layout")

    legend_label = dialog.form_layout.labelForField(dialog.legend_checkbox)
    assert legend_label is not None
    assert legend_label.text() == "Add Legend"
    assert dialog.legend_checkbox.text() == ""

    source_options_widget = dialog.source_checkbox.parentWidget()
    assert source_options_widget == dialog.source_edit.parentWidget()
    assert dialog.source_checkbox.text() == ""
    source_label = dialog.form_layout.labelForField(source_options_widget)
    assert source_label is not None
    assert source_label.text() == "Source"
    assert not dialog.source_checkbox.isChecked()
    assert not dialog.source_edit.isEnabled()
    dialog.source_checkbox.setChecked(True)
    assert dialog.source_edit.isEnabled()

    paper_options_widget = dialog.paper_size_combo.parentWidget()
    assert paper_options_widget == dialog.paper_orientation_combo.parentWidget()
    assert dialog.form_layout.indexOf(paper_options_widget) >= 0
    paper_format_label = dialog.form_layout.labelForField(paper_options_widget)
    assert paper_format_label is not None
    assert paper_format_label.text() == "Paper Format"

    assert dialog.get_paper_size_name() == "a3_landscape"
    dialog.paper_size_combo.setCurrentIndex(dialog.paper_size_combo.findData("a4"))
    assert dialog.get_paper_size_name() == "a4_landscape"
    dialog.paper_orientation_combo.setCurrentIndex(
        dialog.paper_orientation_combo.findData("portrait")
    )
    assert dialog.get_paper_size_name() == "a4_portrait"

    for size in ("a0", "a1", "a2", "a3", "a4"):
        for orientation in ("landscape", "portrait"):
            dialog.paper_size_combo.setCurrentIndex(
                dialog.paper_size_combo.findData(size)
            )
            dialog.paper_orientation_combo.setCurrentIndex(
                dialog.paper_orientation_combo.findData(orientation)
            )
            assert dialog.get_paper_size_name() == f"{size}_{orientation}"

    dialog.paper_size_combo.setCurrentIndex(dialog.paper_size_combo.findData("a3"))
    dialog.paper_orientation_combo.setCurrentIndex(
        dialog.paper_orientation_combo.findData("landscape")
    )
    assert dialog.get_add_legend()
    dialog.legend_checkbox.setChecked(False)
    assert not dialog.get_add_legend()
    dialog.legend_checkbox.setChecked(True)
    assert dialog.get_add_legend()


def test_layout_dialog_initializes_drafter_and_checker_dates(clean_project) -> None:
    dialog = NewLayoutDialog(clean_project, "Test Layout")

    assert dialog.get_drafter_initials() == "XY"
    assert dialog.get_drafter_date() == datetime.now().astimezone().strftime("%d.%m.%Y")
    assert dialog.get_checker_initials() == ""
    assert dialog.get_checker_date() == ""

    drafter_row = dialog.drafter_edit.parentWidget()
    checker_row = dialog.checker_edit.parentWidget()
    drafter_label = dialog.form_layout.labelForField(drafter_row)
    checker_label = dialog.form_layout.labelForField(checker_row)
    assert drafter_label is not None
    assert drafter_label.text() == QCoreApplication.translate("PrintLayout", "Drafter")
    assert checker_label is not None
    assert checker_label.text() == QCoreApplication.translate("PrintLayout", "Checker")
    assert dialog.drafter_date_edit.parentWidget() == drafter_row
    assert dialog.checker_date_edit.parentWidget() == checker_row

    dialog.drafter_edit.setText("ab")
    dialog.drafter_date_edit.setText("01.02.2025")
    dialog.checker_edit.setText("cd")
    dialog.checker_date_edit.setText("03.04.2025")

    assert dialog.get_drafter_initials() == "AB"
    assert dialog.get_drafter_date() == "01.02.2025"
    assert dialog.get_checker_initials() == "CD"
    assert dialog.get_checker_date() == "03.04.2025"


def test_auto_dynamic_elements_applies_both_entered_dates(clean_project) -> None:
    layout = QgsPrintLayout(clean_project)
    layout.initializeDefaults()
    doc = _load_template_document()
    items = layout.addItemsFromXml(
        doc.documentElement(),
        doc,
        QgsReadWriteContext(),
        pasteInPlace=False,
    )
    metadata = LayoutMetadata(
        source_visible=False,
        source_text="",
        drafter="AB",
        drafter_date="01.02.2025",
        checker="CD",
        checker_date="03.04.2025",
    )

    _auto_dynamic_elements(items, None, metadata)

    labels = {
        item.id(): item.text() for item in items if isinstance(item, QgsLayoutItemLabel)
    }
    assert labels["gezeichnet - Datum"] == "01.02.2025"
    assert labels["geprüft - Datum"] == "03.04.2025"


def test_add_legend_uses_map_and_title_block_corner(clean_project) -> None:
    layout = QgsPrintLayout(clean_project)
    layout.initializeDefaults()
    map_item = QgsLayoutItemMap(layout)
    layout.addLayoutItem(map_item)
    title_block_bbox = QRectF(100, 50, 40, 30)

    _add_legend_to_layout(layout, map_item, title_block_bbox)

    legend = next(
        item for item in layout.items() if isinstance(item, QgsLayoutItemLegend)
    )
    assert legend.title() == "Legende"
    assert legend.linkedMap() == map_item
    assert legend.legendFilterByMapEnabled()
    assert legend.frameEnabled()
    assert legend.referencePoint() == QgsLayoutItem.ReferencePoint.LowerRight
    group_style = legend.rstyle(QgsLegendStyle.Group)
    assert group_style.indent() == 4
    assert group_style.margin(QgsLegendStyle.Top) == 6
    assert group_style.margin(QgsLegendStyle.Bottom) == 1
    assert (
        legend.rstyle(QgsLegendStyle.Subgroup).margin(QgsLegendStyle.Bottom)
        == 1
    )
    assert (
        legend.rstyle(QgsLegendStyle.SymbolLabel).margin(QgsLegendStyle.Left)
        == 3
    )
    assert (
        legend.rstyle(QgsLegendStyle.Title)
        .textFormat()
        .font()
        .underline()
    )
    assert legend.positionWithUnits().x() == pytest.approx(title_block_bbox.right())
    assert legend.positionWithUnits().y() == pytest.approx(title_block_bbox.top())


def test_add_legend_applies_scaling(clean_project) -> None:
    layout = QgsPrintLayout(clean_project)
    layout.initializeDefaults()
    map_item = QgsLayoutItemMap(layout)
    layout.addLayoutItem(map_item)

    _add_legend_to_layout(layout, map_item, QRectF(100, 50, 40, 30), 0.75)

    legend = next(
        item for item in layout.items() if isinstance(item, QgsLayoutItemLegend)
    )
    assert legend.scale() == pytest.approx(0.75)
    assert legend.positionWithUnits().x() == pytest.approx(140)
    assert legend.positionWithUnits().y() == pytest.approx(50)


@pytest.mark.parametrize(
    ("paper_size", "expected_title_block_scaling", "expected_legend_scaling"),
    [
        ("a3_landscape", 0.9, 0.9),
        ("a3_portrait", 0.9, 0.9),
        ("a4_landscape", 0.75, 0.75),
        ("a4_portrait", 0.75, 0.75),
        ("a2_landscape", 1.0, 1.0),
    ],
)
def test_paper_size_layout_item_scaling(
    paper_size, expected_title_block_scaling, expected_legend_scaling
) -> None:
    paper_props = getattr(PAPER_SIZES, paper_size)
    assert paper_props.title_block_scaling == expected_title_block_scaling
    assert paper_props.legend_scaling == expected_legend_scaling


def test_scale_title_block_template_scales_group_geometry_and_text(
    clean_project,
) -> None:
    doc = _load_template_document()
    _scale_title_block_template(doc, 0.75)

    layout = QgsPrintLayout(clean_project)
    layout.initializeDefaults()
    items = layout.addItemsFromXml(
        doc.documentElement(),
        doc,
        QgsReadWriteContext(),
        pasteInPlace=False,
    )

    title_block = next(
        item for item in items if isinstance(item, QgsLayoutItemGroup)
    )
    assert title_block.sizeWithUnits().width() == pytest.approx(138.75)
    assert title_block.sizeWithUnits().height() == pytest.approx(72.93)

    frame = next(item for item in items if item.id() == "Plankopf")
    source_label = next(item for item in items if item.id() == "Quelle")
    title_block_bbox = _move_title_block_to_corner(items, 420, 297)
    assert title_block_bbox is not None
    assert title_block_bbox.width() == pytest.approx(138.75)
    assert title_block_bbox.height() == pytest.approx(69.93)
    assert title_block_bbox.right() == pytest.approx(415)
    assert title_block_bbox.bottom() == pytest.approx(292)
    assert frame.sceneBoundingRect().right() == pytest.approx(415)
    assert frame.sceneBoundingRect().bottom() == pytest.approx(292)
    assert source_label.sceneBoundingRect().bottom() == pytest.approx(295)

    drafter_label = next(
        item
        for item in items
        if isinstance(item, QgsLayoutItemLabel) and "gezeichnet" in item.id()
    )
    assert drafter_label.sizeWithUnits().width() == pytest.approx(11.25)
    assert drafter_label.textFormat().size() == pytest.approx(7.5)
