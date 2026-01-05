"""Module: context.py

This module contains the PluginContext class, which serves as a centralized
access point for shared plugin objects such as the QGIS interface, the
current project, and the plugin directory.
"""

from pathlib import Path

from qgis.core import QgsProject
from qgis.gui import QgisInterface, QgsMessageBar
from qgis.PyQt.QtCore import QCoreApplication

from .logs_and_errors import raise_runtime_error, raise_user_error


class PluginContext:
    """Singleton-like storage for plugin-wide context."""

    _iface: QgisInterface | None = None
    _plugin_dir: Path | None = None

    @classmethod
    def init(cls, iface: QgisInterface, plugin_dir: Path) -> None:
        """Initialize with the QGIS interface and plugin directory."""
        cls._iface = iface
        cls._plugin_dir = plugin_dir

    @classmethod
    def iface(cls) -> QgisInterface:
        """Get the QGIS interface. Raises error if not initialized."""
        if cls._iface is None:
            raise_runtime_error("PluginContext not initialized with iface.")
        return cls._iface

    @classmethod
    def project(cls) -> QgsProject:
        """Return the current QGIS project instance."""
        project = QgsProject.instance()
        if project is None:
            raise_runtime_error("No QGIS project is currently open.")
        return project

    @classmethod
    def message_bar(cls) -> QgsMessageBar | None:
        """Get the QGIS message bar."""
        return cls._iface.messageBar() if cls._iface else None

    @classmethod
    def plugin_dir(cls) -> Path:
        """Get the plugin directory."""
        if cls._plugin_dir is None:
            raise_runtime_error("PluginContext not initialized with plugin_dir.")
        return cls._plugin_dir

    @classmethod
    def project_path(cls) -> Path:
        r"""Get the file path of the current QGIS project.

        Returns:
            Path: The path to the current QGIS project file
                (e.g., 'C:\project\my_project.qgz').
        """
        project: QgsProject = cls.project()
        project_path: str = project.fileName()
        if not project_path:
            # fmt: off
            msg: str = QCoreApplication.translate("UserError", "Project is not saved. Please save the project first.")  # noqa: E501
            # fmt: on
            raise_user_error(msg)

        return Path(project_path)

    @classmethod
    def project_gpkg(cls) -> Path:
        """Return the expected GeoPackage path for the current project.

        Example: for a project 'my_project.qgz', returns 'my_project.gpkg'.

        :returns: The Path object to the GeoPackage.
        """
        return cls.project_path().with_suffix(".gpkg")
