"""Module: constants.py

This module contains shared constants and enumerations used across the plugin.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from qgis.core import Qgis, QgsMapLayer
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

RESOURCES_PATH: Path = Path(__file__).parent.parent / "resources"


# pylint: disable=too-few-public-methods
class Icons:
    """Holds plugin icons."""

    @staticmethod
    def _qicon(filename: str) -> QIcon:
        """Load an icon from the icons directory."""
        return QIcon(str(RESOURCES_PATH / "icons" / filename))

    def __init__(self) -> None:
        """Initialize the icons."""

        self.main_icon: QIcon = self._qicon("main_icon.svg")

        self.main_menu_move: QIcon = self._qicon("main_menu_move.svg")
        self.main_menu_rename_move: QIcon = self._qicon("main_menu_rename_move.svg")
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


ICONS = Icons()


@dataclass
class LayerLocationInfo:
    """Holds display information for a layer's location."""

    icon: QIcon
    _tooltip_factory: Callable[[], str]

    @property
    def tooltip(self) -> str:
        """Generate and return the translated tooltip.

        Returns:
            The translated tooltip string.
        """
        return self._tooltip_factory()


# fmt: off
# ruff: noqa: E501
class LayerLocation(LayerLocationInfo, Enum):
    """Enumeration for layer locations with associated display info."""

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
