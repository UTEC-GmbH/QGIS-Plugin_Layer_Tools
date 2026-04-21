"""Module: print_layout_export.py

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
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QSpinBox,
    QToolButton,
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

        # -- Export Settings Section --
        self.settings_toggle: QToolButton = QToolButton()
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(False)

        # Setup visual styles based on Qt version
        if PluginContext.is_qt6():
            self.settings_toggle.setArrowType(Qt.ArrowType.RightArrow)
            style = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            shape = QFrame.Shape.StyledPanel
        else:
            self.settings_toggle.setArrowType(Qt.RightArrow)
            style = Qt.ToolButtonTextBesideIcon
            shape = QFrame.StyledPanel

        self.settings_toggle.setToolButtonStyle(style)
        self.settings_toggle.setText(
            QCoreApplication.translate("PrintLayout", "Export Settings")
        )
        self.settings_toggle.setStyleSheet("border: none; font-weight: bold;")
        self.settings_toggle.toggled.connect(self._toggle_settings)

        self.main_container.addWidget(self.settings_toggle)

        self.settings_container: QFrame = QFrame()
        self.settings_container.setFrameShape(shape)
        self.settings_container.setVisible(False)
        self.settings_form: QFormLayout = QFormLayout(self.settings_container)

        # DPI Setting
        self.dpi_spin: QSpinBox = QSpinBox()
        self.dpi_spin.setRange(72, 3000)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setSuffix(" dpi")
        self.settings_form.addRow(
            QCoreApplication.translate("PrintLayout", "Resolution:"), self.dpi_spin
        )

        # Georeference Setting
        self.georef_check: QCheckBox = QCheckBox()
        self.georef_check.setChecked(True)
        self.settings_form.addRow(
            QCoreApplication.translate("PrintLayout", "Append georeference:"),
            self.georef_check,
        )

        # Metadata Setting
        self.metadata_check: QCheckBox = QCheckBox()
        self.metadata_check.setChecked(True)
        self.settings_form.addRow(
            QCoreApplication.translate("PrintLayout", "Export metadata:"),
            self.metadata_check,
        )

        self.main_container.addWidget(self.settings_container)

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

    def _toggle_settings(self, *, expanded: bool) -> None:
        """Toggle the visibility of the export settings section.

        Args:
            expanded: True if the settings section should be visible.
        """
        self.settings_container.setVisible(expanded)

        if PluginContext.is_qt6():
            arrow = Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        else:
            arrow = Qt.DownArrow if expanded else Qt.RightArrow

        self.settings_toggle.setArrowType(arrow)

    def get_export_settings(self) -> QgsLayoutExporter.PdfExportSettings:
        """Retrieve the PDF export settings configured in the dialog.

        Returns:
            QgsLayoutExporter.PdfExportSettings: The configured export settings.
        """
        settings = QgsLayoutExporter.PdfExportSettings()
        settings.dpi = float(self.dpi_spin.value())
        settings.appendGeoreference = self.georef_check.isChecked()
        settings.exportMetadata = self.metadata_check.isChecked()

        return settings


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

    # Retrieve settings once for all layouts
    export_settings: QgsLayoutExporter.PdfExportSettings = dialog.get_export_settings()

    try:
        for index, layout in enumerate(selected_layouts):
            layout_name: str = layout.name()
            results.processed.append(layout_name)
            pdf_path: Path = pdf_dir / f"{layout_name}.pdf"

            # Archive existing file if it exists
            _archive_existing_pdf(pdf_path)

            status: QgsLayoutExporter.ExportResult = QgsLayoutExporter(
                layout
            ).exportToPdf(str(pdf_path), export_settings)

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
