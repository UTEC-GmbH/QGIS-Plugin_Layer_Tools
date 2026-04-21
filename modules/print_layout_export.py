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
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
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
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        self.main_container: QVBoxLayout = QVBoxLayout(self)

        self._setup_layout_list(layouts)
        self._setup_settings_section()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.main_container.addWidget(self.button_box)

    def _setup_layout_list(self, layouts: list[QgsPrintLayout]) -> None:
        """Set up the layout selection list.

        Args:
            layouts: List of available print layouts.
        """
        self.list_widget: QListWidget = QListWidget()

        for layout in layouts:
            item = QListWidgetItem(layout.name())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, layout)
            self.list_widget.addItem(item)

        self.main_container.addWidget(self.list_widget)

    def _setup_settings_section(self) -> None:
        """Set up the collapsible export settings section."""
        self.settings_toggle: QToolButton = QToolButton()
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(False)

        # Setup visual styles based on Qt version
        is_qt6: bool = PluginContext.is_qt6()
        arrow = Qt.ArrowType.RightArrow if is_qt6 else Qt.RightArrow
        style = (
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            if is_qt6
            else Qt.ToolButtonTextBesideIcon
        )
        shape = QFrame.Shape.StyledPanel if is_qt6 else QFrame.StyledPanel

        self.settings_toggle.setArrowType(arrow)
        self.settings_toggle.setToolButtonStyle(style)
        self.settings_toggle.setText(
            QCoreApplication.translate("PrintLayout", "Export Settings")
        )
        self.settings_toggle.setStyleSheet("border: none; font-weight: bold;")
        self.settings_toggle.toggled.connect(
            lambda checked: self._toggle_settings(expanded=checked)
        )

        self.main_container.addWidget(self.settings_toggle)

        self.settings_container: QFrame = QFrame()
        self.settings_container.setFrameShape(shape)
        self.settings_container.setVisible(False)
        self.settings_form: QFormLayout = QFormLayout(self.settings_container)

        self._setup_folder_selection()
        self._setup_export_options()

        self.main_container.addWidget(self.settings_container)

    def _setup_folder_selection(self) -> None:
        """Add the folder selection widgets to the settings form."""
        self.dir_edit: QLineEdit = QLineEdit()
        default_dir: Path = PluginContext.project_path().parent / "pdf"
        self.dir_edit.setText(str(default_dir))

        self.dir_button: QToolButton = QToolButton()
        self.dir_button.setText("...")
        self.dir_button.clicked.connect(self._select_directory)

        self.dir_layout: QHBoxLayout = QHBoxLayout()
        self.dir_layout.addWidget(self.dir_edit)
        self.dir_layout.addWidget(self.dir_button)

        self.settings_form.addRow(
            QCoreApplication.translate("PrintLayout", "Export Folder:"),
            self.dir_layout,
        )

    def _setup_export_options(self) -> None:
        """Add DPI and checkbox options to the settings form."""

        # fmt: off
        # ruff: noqa: E501
        resolution_label: str = QCoreApplication.translate("PrintLayout", "Resolution")
        georef_label: str = QCoreApplication.translate("PrintLayout", "Append georeference information")
        georef_tooltip: str = QCoreApplication.translate("PrintLayout", "Include georeferencing information in the PDF header. Allows compatible viewers to display coordinates.")
        metadata_label: str = QCoreApplication.translate("PrintLayout", "Export metadata")
        metadata_tooltip: str = QCoreApplication.translate("PrintLayout", "Include document metadata (author, title, etc.) in the PDF.")
        simplify_label: str = QCoreApplication.translate("PrintLayout", "Simplify geometry")
        simplify_tooltip: str = QCoreApplication.translate("PrintLayout", "Simplify geometry to reduce file size.")
        # fmt: on

        # Resolution
        self.dpi_spin: QSpinBox = QSpinBox()
        self.dpi_spin.setRange(72, 3000)
        self.dpi_spin.setValue(200)
        self.dpi_spin.setSuffix(" dpi")
        self.settings_form.addRow(resolution_label, self.dpi_spin)

        # Georeference
        self.georef_check = self._add_setting_checkbox(georef_label, georef_tooltip)
        self.metadata_check = self._add_setting_checkbox(
            metadata_label, metadata_tooltip
        )

        # Simplify geometry
        self.simplify_geom_check: QCheckBox = self._add_setting_checkbox(
            simplify_label, simplify_tooltip
        )

    def _add_setting_checkbox(self, label_text: str, tooltip_text: str) -> QCheckBox:
        """Add a checkbox row to the export settings form.

        Args:
            label_text: The translated text for the form row label.
            tooltip_text: The translated text for the widget tooltip.

        Returns:
            QCheckBox: The created checkbox widget.
        """
        checkbox: QCheckBox = QCheckBox()
        checkbox.setChecked(True)
        checkbox.setToolTip(tooltip_text)
        self.settings_form.addRow(label_text, checkbox)

        return checkbox

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

    def _select_directory(self) -> None:
        """Open a directory selection dialog and update the path."""
        if selected_directory := QFileDialog.getExistingDirectory(
            self,
            QCoreApplication.translate("PrintLayout", "Select Export Directory"),
            self.dir_edit.text(),
        ):
            self.dir_edit.setText(selected_directory)

    def get_export_directory(self) -> Path:
        """Retrieve the selected export directory.

        Returns:
            Path: The path to the folder where PDFs will be saved.
        """
        return Path(self.dir_edit.text().strip())

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
        settings.simplifyGeometries = self.simplify_geom_check.isChecked()

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


def export_layouts_to_pdf() -> ActionResults[None] | None:
    """Export selected layouts from the project to PDF files.

    Shows a dialog to the user to select which layouts to export.
    The PDFs are saved in a 'pdf' subfolder within the project directory.

    Returns:
        ActionResults[None] | None: The summary of results, or None if cancelled.
    """
    project: QgsProject = PluginContext.project()
    if (layout_manager := project.layoutManager()) is None:
        raise_runtime_error("Project has no layout manager")

    layouts: list[QgsPrintLayout] = layout_manager.printLayouts()
    if not layouts:
        raise_runtime_error("No layouts found in the project.")

    dialog: LayoutSelectionDialog = LayoutSelectionDialog(layouts)
    if not dialog.exec_():
        return None

    if not (selected_layouts := dialog.get_selected_layouts()):
        return None

    # Retrieve settings and directory once for all layouts
    export_settings: QgsLayoutExporter.PdfExportSettings = dialog.get_export_settings()
    pdf_dir: Path = dialog.get_export_directory()
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
