"""Unit tests for PDF layout export failure handling."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from modules.print_layout_export import export_layouts_to_pdf


def test_export_skips_existing_pdf_when_archiving_fails(tmp_path: Path) -> None:
    """An existing PDF must not be overwritten when it cannot be archived."""
    pdf_path = tmp_path / "existing.pdf"
    pdf_path.write_text("original", encoding="utf-8")

    layout = MagicMock()
    layout.name.return_value = "Plan"
    project = MagicMock()
    project.layoutManager.return_value.printLayouts.return_value = [layout]
    dialog = MagicMock()
    dialog.get_selected_layouts.return_value = [layout]
    dialog.get_export_directory.return_value = tmp_path
    dialog.get_export_filename.return_value = pdf_path.name

    with (
        patch("modules.print_layout_export.PluginContext.project", return_value=project),
        patch(
            "modules.print_layout_export.LayoutSelectionDialog", return_value=dialog
        ),
        patch("modules.print_layout_export.exec_dialog", return_value=1),
        patch(
            "modules.print_layout_export._archive_existing_pdf",
            return_value=False,
        ),
        patch(
            "modules.print_layout_export.PluginContext.message_bar",
            return_value=None,
        ),
        patch("modules.print_layout_export.QgsLayoutExporter") as exporter,
    ):
        results = export_layouts_to_pdf()

    assert results is not None
    assert results.errors[0].issue == (
        "Could not archive the existing PDF; export was skipped."
    )
    exporter.assert_not_called()
    assert pdf_path.read_text(encoding="utf-8") == "original"
