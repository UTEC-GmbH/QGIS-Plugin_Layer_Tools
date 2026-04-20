"""Module: layout_export.py

This module handles the batch export of QGIS print layouts to PDF files.
"""

from pathlib import Path

from qgis.core import (
    Qgis,
    QgsLayoutExporter,
    QgsPrintLayout,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
)

from .constants import ActionResults, Issue
from .context import PluginContext
from .logs_and_errors import log_debug, raise_runtime_error


class LayoutSelectionDialog(QDialog):
    """Dialog for selecting which layouts to export as PDF."""

    def __init__(self, layouts: list[QgsPrintLayout]) -> None:
        """Initialize the selection dialog.

        Args:
            layouts: List of available print layouts in the project.
        """
        super().__init__(PluginContext.iface().mainWindow())
        self.setWindowTitle(
            QCoreApplication.translate("PrintLayout", "Export Layouts as PDF")
        )
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        self.main_container: QVBoxLayout = QVBoxLayout(self)
        self.list_widget: QListWidget = QListWidget()

        for layout in layouts:
            item = QListWidgetItem(layout.name())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, layout)
            self.list_widget.addItem(item)

        self.main_container.addWidget(self.list_widget)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.main_container.addWidget(self.button_box)

    def get_selected_layouts(self) -> list[QgsPrintLayout]:
        """Retrieve the list of selected layout objects.

        Returns:
            list[QgsPrintLayout]: List of layout objects selected by the user.
        """
        return [
            item.data(Qt.UserRole)
            for index in range(self.list_widget.count())
            if (item := self.list_widget.item(index)) is not None
            and item.checkState() == Qt.Checked
        ]


def _archive_existing_pdf(pdf_path: Path) -> None:
    """Move an existing PDF to an 'alt' subfolder, versioning it if necessary.

    Args:
        pdf_path: The path to the PDF file that should be archived.
    """
    if not pdf_path.exists():
        return

    alt_directory: Path = pdf_path.parent / "alt"
    alt_directory.mkdir(exist_ok=True)

    target_file_path: Path = alt_directory / pdf_path.name

    # If the file already exists in the archive, find a unique name with a suffix
    if target_file_path.exists():
        stem: str = pdf_path.stem
        extension: str = pdf_path.suffix
        iteration: int = 2
        while (
            target_file_path := alt_directory / f"{stem} ({iteration}){extension}"
        ).exists():
            iteration += 1

    try:
        pdf_path.rename(target_file_path)
    except OSError as error:
        log_debug(f"Could not archive existing file: {error}", Qgis.Warning)


def export_layouts_to_pdf() -> ActionResults[None]:
    """Export selected layouts from the project to PDF files.

    Shows a dialog to the user to select which layouts to export.
    The PDFs are saved in a 'pdf' subfolder within the project directory.

    Returns:
        ActionResults: The summary of processed, successful, and failed exports.
    """
    project: QgsProject = PluginContext.project()
    if (layout_manager := project.layoutManager()) is None:
        raise_runtime_error("Project has no layout manager")

    layouts: list[QgsPrintLayout] = layout_manager.printLayouts()
    if not layouts:
        raise_runtime_error("No layouts found in the project.")

    dialog = LayoutSelectionDialog(layouts)
    if not dialog.exec_():
        return ActionResults(None, skips=[Issue("User", "Export cancelled by user.")])

    selected_layouts: list[QgsPrintLayout] = dialog.get_selected_layouts()
    if not selected_layouts:
        return ActionResults(None, skips=[Issue("User", "No layouts selected.")])

    pdf_dir: Path = PluginContext.project_path().parent / "pdf"
    pdf_dir.mkdir(exist_ok=True)

    results: ActionResults[None] = ActionResults(None)
    progress_bar = QProgressBar()
    progress_bar.setMaximum(len(selected_layouts))
    progress_bar.setValue(0)

    if message_bar := PluginContext.message_bar():
        message_bar.pushWidget(progress_bar, Qgis.Info)

    try:
        for index, layout in enumerate(selected_layouts):
            layout_name: str = layout.name()
            results.processed.append(layout_name)
            pdf_path: Path = pdf_dir / f"{layout_name}.pdf"

            # Archive existing file if it exists
            _archive_existing_pdf(pdf_path)

            status: QgsLayoutExporter.ExportResult = QgsLayoutExporter(
                layout
            ).exportToPdf(str(pdf_path), QgsLayoutExporter.PdfExportSettings())

            if (
                PluginContext.is_qgis4()
                and status == QgsLayoutExporter.ExportResult.Success
            ) or (not PluginContext.is_qgis4() and status == QgsLayoutExporter.Success):
                results.successes.append(layout_name)
                log_debug(
                    f"Exported layout '{layout_name}' to {pdf_path}", Qgis.Success
                )
            else:
                results.errors.append(
                    Issue(layout_name, f"Export failed with error code: {status}")
                )
                log_debug(
                    f"Failed to export layout '{layout_name}'. Error code: {status}",
                    Qgis.Warning,
                )

            progress_bar.setValue(index + 1)
            QCoreApplication.processEvents()
    finally:
        if message_bar := PluginContext.message_bar():
            message_bar.clearWidgets()

    return results
