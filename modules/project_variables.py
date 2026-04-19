"""Module: project_variables.py

This module handles the management of custom UTEC project variables.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from qgis.core import QgsExpressionContextUtils, QgsProject
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTextEdit,
)

from .context import PluginContext
from .general import enforce_text_edit_limits
from .logs_and_errors import log_debug


@dataclass
class ProjectVariable:
    """Definition of a custom UTEC project variable."""

    id: str
    label: str
    default_callback: Callable[[QgsProject], str]
    is_multi_line: bool = False
    max_lines: int | None = None
    max_chars_per_line: int | None = None

    @property
    def name(self) -> str:
        """Return the variable name with the required prefix."""
        return f"UTEC_{self.id}"


def get_default_number(project: QgsProject) -> str:
    """Extract leading digits from project filename or return '9999'."""
    if (path := project.fileName()) and (match := re.match(r"^\d+", Path(path).stem)):
        return match.group()
    return "9999"


def get_project_variables() -> list[ProjectVariable]:
    """Return the definition of custom UTEC project variables.

    This function ensures that labels are translated at runtime,
    reflecting the current QGIS locale settings.

    Returns:
        list[ProjectVariable]: A list of ProjectVariable definitions.
    """
    # fmt: off
    # ruff: noqa: E501
    return [
        ProjectVariable(
            id="project_number",
            label=QCoreApplication.translate("ProjectVariables", "Project Number:"),
            max_chars_per_line=8,
            default_callback=get_default_number,
        ),
        ProjectVariable(
            id="project_developer",
            label=QCoreApplication.translate("ProjectVariables", "Project Developer:"),
            default_callback=lambda _: QCoreApplication.translate("ProjectVariables", "Developer"),
            is_multi_line=True,
            max_lines=3,
            max_chars_per_line=45,
        ),
        ProjectVariable(
            id="project_name",
            label=QCoreApplication.translate("ProjectVariables", "Project Name:"),
            default_callback=lambda _: QCoreApplication.translate("ProjectVariables", "Project"),
            is_multi_line=True,
            max_lines=3,
            max_chars_per_line=30,
        ),
    ]
    # fmt: on


def get_current_variable_value(project: QgsProject, variable: ProjectVariable) -> str:
    """Retrieve the current variable value or its default.

    Args:
        project: The QGIS project.
        variable: The variable definition.

    Returns:
        The current value if set, otherwise the default value.
    """
    # Try to get existing value from project scope
    if not (scope := QgsExpressionContextUtils.projectScope(project)):
        log_debug("Project scope not found.")
        return ""

    if existing_value := scope.variable(variable.name):
        return str(existing_value)

    return variable.default_callback(project)


class ProjectVariablesDialog(QDialog):
    """Dialog for editing UTEC project variables."""

    def __init__(self, project: QgsProject) -> None:
        """Initialize the dialog.

        Args:
            project: The current QGIS project.
        """
        super().__init__(PluginContext.iface().mainWindow())
        self.project: QgsProject = project
        self.setWindowTitle(
            QCoreApplication.translate("ProjectVariables", "Edit Project Variables")
        )
        self.setMinimumWidth(400)

        self.layout: QFormLayout = QFormLayout(self)
        self.edits: dict[str, QLineEdit | QTextEdit] = {}
        self.variables: list[ProjectVariable] = get_project_variables()

        for variable in self.variables:
            edit: QLineEdit | QTextEdit
            if variable.is_multi_line:
                edit = QTextEdit()
                edit.setAcceptRichText(False)
                edit.setTabChangesFocus(True)
                edit.setPlainText(get_current_variable_value(self.project, variable))
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
                edit.setText(get_current_variable_value(self.project, variable))
                if variable.max_chars_per_line:
                    edit.setMaxLength(variable.max_chars_per_line)

            self.edits[variable.id] = edit
            label_text: str = f"{variable.label} ({variable.name})"
            self.layout.addRow(label_text, edit)

        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addRow(self.button_box)

    def save_variables(self) -> None:
        """Write the values from the UI back to the project properties."""
        for variable in self.variables:
            widget: QLineEdit | QTextEdit = self.edits[variable.id]
            value: str = ""
            if isinstance(widget, QLineEdit):
                value = widget.text().strip()
            elif isinstance(widget, QTextEdit):
                value = widget.toPlainText().strip()

            QgsExpressionContextUtils.setProjectVariable(
                self.project, variable.name, value
            )

        log_debug("Project variables updated.", prefix="Project Properties → ")


def edit_project_variables() -> None:
    """Open the project variables editor dialog.

    This function orchestrates the process of reading, editing and
    saving project-specific metadata.
    """
    project: QgsProject = PluginContext.project()

    # Ensure project is saved to calculate default project number from filename
    if not project.fileName():
        # Trigger PluginContext validation
        PluginContext.project_path()

    dialog = ProjectVariablesDialog(project)
    if dialog.exec_():
        dialog.save_variables()
        # Mark project as dirty so user is prompted to save changes
        project.setDirty(True)
    else:
        log_debug("Variable editing cancelled by user.")
