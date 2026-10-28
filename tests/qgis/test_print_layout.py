"""Tests for print layout creation options."""

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
from qgis.PyQt.QtCore import QRectF

from modules.constants import PAPER_SIZES
from modules.print_layout import (
    NewLayoutDialog,
    _add_legend_to_layout,
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
    assert group_style.margin(QgsLegendStyle.Top) == 6
    assert group_style.margin(QgsLegendStyle.Bottom) == 1
    assert (
        legend.rstyle(QgsLegendStyle.Title)
        .textFormat()
        .font()
        .underline()
    )
    assert legend.positionWithUnits().x() == pytest.approx(title_block_bbox.right())
    assert legend.positionWithUnits().y() == pytest.approx(title_block_bbox.top())


@pytest.mark.parametrize(
    ("paper_size", "expected_scaling"),
    [
        ("a3_landscape", 0.9),
        ("a3_portrait", 0.9),
        ("a4_landscape", 0.75),
        ("a4_portrait", 0.75),
        ("a2_landscape", 1.0),
    ],
)
def test_paper_size_title_block_scaling(paper_size, expected_scaling) -> None:
    assert getattr(PAPER_SIZES, paper_size).title_block_scaling == expected_scaling


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

    title_block_bbox = _move_title_block_to_corner(items, 420, 297)
    assert title_block_bbox is not None
    assert title_block_bbox.width() == pytest.approx(138.75)
    assert title_block_bbox.height() == pytest.approx(72.93)
    assert title_block_bbox.right() == pytest.approx(415)
    assert title_block_bbox.bottom() == pytest.approx(296)

    drafter_label = next(
        item
        for item in items
        if isinstance(item, QgsLayoutItemLabel) and "gezeichnet" in item.id()
    )
    assert drafter_label.sizeWithUnits().width() == pytest.approx(11.25)
    assert drafter_label.textFormat().size() == pytest.approx(7.5)
