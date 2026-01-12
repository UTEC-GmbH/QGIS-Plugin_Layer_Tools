"""Module: constants.py

This module contains shared constants and enumerations used across the plugin.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar

from qgis.core import Qgis, QgsApplication, QgsMapLayer
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

GEOMETRY_SUFFIX_MAP: dict[Qgis.GeometryType, str] = {
    Qgis.GeometryType.Line: "l",
    Qgis.GeometryType.Point: "pt",
    Qgis.GeometryType.Polygon: "pg",
}

LAYER_TYPES: dict = {
    QgsMapLayer.VectorLayer: "VectorLayer",
    QgsMapLayer.RasterLayer: "RasterLayer",
    QgsMapLayer.PluginLayer: "PluginLayer",
}


@dataclass
class Issue:
    """Represents a problem associated with a specific layer.

    Attributes:
        layer (str): The layer name.
        issue (str): The issue description.
    """

    layer: str
    issue: str

    def __str__(self) -> str:
        """Return a string representation of the Issue object."""
        return f"Layer: '{self.layer}': {self.issue}"


T = TypeVar("T")


@dataclass
class ActionResults(Generic[T]):
    """Holds the results of an action.

    Attributes:
        result (T | None): The result of the action.
        processed (list[str]): A list of layer names that were processed.
        successes (list[str]): A list of layer names that were successfully processed.
        skips (list[Issue]): A list of skipped layers and the reason for skipping.
        errors (list[Issue]): A list of errors that occurred during the action.
    """

    result: T
    processed: list[str] = field(default_factory=list)
    successes: list[str] = field(default_factory=list)
    skips: list[Issue] = field(default_factory=list)
    errors: list[Issue] = field(default_factory=list)


RESOURCES_PATH: Path = Path(__file__).parent.parent / "resources"
ICONS_PATH: Path = RESOURCES_PATH / "icons"


# pylint: disable=too-few-public-methods
class Icons:
    """Holds plugin icons."""

    @staticmethod
    def _qicon(filename: str) -> QIcon:
        """Load an icon from the icons directory.

        Args:
            filename: The name of the icon file (including extension).

        Returns:
            QIcon: The loaded QIcon object.
        """
        return QIcon(str(ICONS_PATH / filename))

    def __init__(self) -> None:
        """Initialize the icons."""

        self.main_icon: QIcon = self._qicon("main_icon.svg")

        self.main_menu_copy: QIcon = self._qicon("main_menu_copy.svg")
        self.main_menu_rename_copy: QIcon = self._qicon("main_menu_rename_copy.svg")
        self.main_menu_rename: QIcon = self._qicon("main_menu_rename.svg")
        self.main_menu_send: QIcon = self._qicon("main_menu_send.svg")
        self.main_menu_undo: QIcon = self._qicon("main_menu_undo.svg")

        self.location_cloud: QIcon = self._qicon("location_cloud.svg")
        self.location_empty: QIcon = self._qicon("location_empty.svg")
        self.location_external: QIcon = self._qicon("location_external.svg")
        self.location_folder_no_gpkg: QIcon = self._qicon("location_folder_no_gpkg.svg")
        self.location_gpkg_folder: QIcon = self._qicon("location_gpkg_folder.svg")
        self.location_gpkg_project: QIcon = self._qicon("location_gpkg_project.svg")
        self.location_unknown: QIcon = self._qicon("location_unknown.svg")

        self.gpkg_project: QIcon = self._qicon("gpkg_project.svg")
        self.gpkg_used: QIcon = QgsApplication.getThemeIcon("mActionLink.svg")
        self.gpkg_unused: QIcon = QgsApplication.getThemeIcon("mActionUnlink.svg")


ICONS = Icons()


class LayerLocation(Enum):
    """Enumeration for layer locations with associated display info."""

    # fmt: off
    # ruff: noqa: E501
    CLOUD = (
        ICONS.location_cloud,
        lambda: QCoreApplication.translate("LayerLocation", "<p>🔗<b>Cloud Layer</b>🔗</p>This layer is from a cloud-based service or database.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    EMPTY = (
        ICONS.location_empty,
        lambda: QCoreApplication.translate("LayerLocation", "<p>❓<b>Empty Layer</b>❓</p>This Layer does not contain any objects.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    EXTERNAL = (
        ICONS.location_external,
        lambda: QCoreApplication.translate("LayerLocation", "<p>💥💥💥<b>Caution</b>💥💥💥</p>This layer is stored outside the project folder. Please move to the project folder.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    FOLDER_NO_GPKG = (
        ICONS.location_folder_no_gpkg,
        lambda: QCoreApplication.translate("LayerLocation", "<p>⚠️<b>Layer in Project Folder but not GeoPackage</b>⚠️</p>This layer is stored in the project folder, but not in a GeoPackage. Consider saving to the Project-GeoPackage (a GeoPackage with the same name as the project file).<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    GPKG_FOLDER = (
        ICONS.location_gpkg_folder,
        lambda: QCoreApplication.translate("LayerLocation", "<p>⚠️<b>Layer in GeoPackge in Project Folder</b>⚠️</p>This layer is stored in a GeoPackage in the project folder, but not in the Project-GeoPackage. Consider saving to the Project-GeoPackage (a GeoPackage with the same name as the project file).<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    GPKG_PROJECT = (
        ICONS.location_gpkg_project,
        lambda: QCoreApplication.translate("LayerLocation", "<p>👍<b>Layer in Project-Geopackage</b>👍</p>This layer is stored in the Project-GeoPackage (a GeoPackage with the same name as the project file).<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    UNKNOWN = (
        ICONS.location_unknown,
        lambda: QCoreApplication.translate("LayerLocation", "<p>❓<b>Data Source Unknown</b>❓</p>The data source of this Layer could not be determined.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    # fmt: on

    def __init__(self, icon: QIcon, tooltip_factory: Callable[[], str]) -> None:
        """Initialize the enum member.

        Args:
            icon: The icon associated with the layer location.
            tooltip_factory: A callable that returns the translated tooltip text.
        """
        self._icon: QIcon = icon
        self._tooltip_factory: Callable[[], str] = tooltip_factory

    @property
    def icon(self) -> QIcon:
        """Return the icon for this location."""
        return self._icon

    @property
    def tooltip(self) -> str:
        """Generate and return the translated tooltip."""
        return self._tooltip_factory()
