"""Module: constants.py

This module contains shared constants and enumerations used across the plugin.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar

from qgis.core import Qgis, QgsApplication, QgsSvgCache
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor, QIcon, QPixmap

GEOMETRY_SUFFIX_MAP: dict[Qgis.GeometryType, str] = {
    Qgis.GeometryType.Line: "l",
    Qgis.GeometryType.Point: "pt",
    Qgis.GeometryType.Polygon: "pg",
}

LAYER_TYPES: dict = {
    Qgis.LayerType.Vector: "VectorLayer",
    Qgis.LayerType.Raster: "RasterLayer",
    Qgis.LayerType.Plugin: "PluginLayer",
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
    def _qicon(
        filename: str,
        *,
        dynamic: bool = False,
        dark: str = "#1c274c",
        light: str = "#738ad5",
    ) -> QIcon:
        """Load an icon from the icons directory.

        Args:
            filename: The name of the icon file (including extension).
            dynamic: Whether to load the icon dynamically (default: False).
            dark: The color to use for the dark theme (default: "#1c274c").
            light: The color to use for the light theme (default: "#738ad5").

        Returns:
            QIcon: The loaded QIcon object.
        """

        if not dynamic:
            return QIcon(str(ICONS_PATH / filename))

        # pylint: disable=import-outside-toplevel
        from .context import PluginContext  # noqa: PLC0415

        is_dark: bool = PluginContext.is_dark_theme()

        fill_colour: QColor = QColor(light) if is_dark else QColor(dark)
        stroke_colour: QColor = QColor(dark) if is_dark else QColor(light)

        svg_chache: QgsSvgCache | None = QgsApplication.svgCache()
        if svg_chache is None:
            return QIcon(str(ICONS_PATH / filename))
        icon, _ = svg_chache.svgAsImage(
            str(ICONS_PATH / filename), 48, fill_colour, stroke_colour, 1, 1
        )

        return QIcon(QPixmap.fromImage(icon))

    def __init__(self) -> None:
        """Initialize the icons."""

        self.main_icon: QIcon = self._qicon("main_icon.svg")

        self.location_empty: QIcon = self._qicon("location_empty.svg")
        self.location_external: QIcon = self._qicon("location_external.svg")
        self.location_folder_no_gpkg: QIcon = self._qicon("location_folder_no_gpkg.svg")
        self.location_gpkg_folder: QIcon = self._qicon("location_gpkg_folder.svg")
        self.location_gpkg_project: QIcon = self._qicon("location_gpkg_project.svg")

        self.browser_gpkg: QIcon = self._qicon("browser_gpkg.svg")
        self.browser_used: QIcon = QgsApplication.getThemeIcon(
            "mActionHandleStoreFilterExpressionChecked.svg"
        )
        self.browser_unused: QIcon = QgsApplication.getThemeIcon(
            "mActionHandleStoreFilterExpressionUnchecked.svg"
        )

    @property
    def main_menu_copy(self) -> QIcon:
        """Return the copy icon, dynamically colored for the current theme."""
        return self._qicon("main_menu_copy.svg", dynamic=True)

    @property
    def main_menu_rename_copy(self) -> QIcon:
        """Return the rename+copy icon, dynamically colored for the current theme."""
        return self._qicon("main_menu_rename_copy.svg", dynamic=True)

    @property
    def main_menu_rename(self) -> QIcon:
        """Return the rename icon, dynamically colored for the current theme."""
        return self._qicon("main_menu_rename.svg", dynamic=True)

    @property
    def main_menu_send(self) -> QIcon:
        """Return the send icon, dynamically colored for the current theme."""
        return self._qicon("main_menu_send.svg", dynamic=True)

    @property
    def main_menu_undo(self) -> QIcon:
        """Return the undo icon, dynamically colored for the current theme."""
        return self._qicon("main_menu_undo.svg", dynamic=True)

    @property
    def location_cloud(self) -> QIcon:
        """Return the cloud icon, dynamically colored for the current theme."""
        return self._qicon("location_cloud.svg", dynamic=True)

    @property
    def location_unknown(self) -> QIcon:
        """Return the unknown icon, dynamically colored for the current theme."""
        return self._qicon("location_unknown.svg", dynamic=True)


ICONS = Icons()


class LayerLocation(Enum):
    """Enumeration for layer locations with associated display info."""

    # fmt: off
    # ruff: noqa: E501
    CLOUD = (
        lambda: ICONS.location_cloud,
        lambda: QCoreApplication.translate("LayerLocation", "<p>🔗<b>Cloud Layer</b>🔗</p>This layer is from a cloud-based service or database.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    EMPTY = (
        lambda: ICONS.location_empty,
        lambda: QCoreApplication.translate("LayerLocation", "<p>❓<b>Empty Layer</b>❓</p>This Layer does not contain any objects.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    EXTERNAL = (
        lambda: ICONS.location_external,
        lambda: QCoreApplication.translate("LayerLocation", "<p>💥💥💥<b>Caution</b>💥💥💥</p>This layer is stored outside the project folder. Please move to the project folder.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    FOLDER_NO_GPKG = (
        lambda: ICONS.location_folder_no_gpkg,
        lambda: QCoreApplication.translate("LayerLocation", "<p>⚠️<b>Layer in Project Folder but not GeoPackage</b>⚠️</p>This layer is stored in the project folder, but not in a GeoPackage. Consider saving to the Project-GeoPackage (a GeoPackage with the same name as the project file).<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    GPKG_FOLDER = (
        lambda: ICONS.location_gpkg_folder,
        lambda: QCoreApplication.translate("LayerLocation", "<p>⚠️<b>Layer in GeoPackge in Project Folder</b>⚠️</p>This layer is stored in a GeoPackage in the project folder, but not in the Project-GeoPackage. Consider saving to the Project-GeoPackage (a GeoPackage with the same name as the project file).<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    GPKG_PROJECT = (
        lambda: ICONS.location_gpkg_project,
        lambda: QCoreApplication.translate("LayerLocation", "<p>👍<b>Layer in Project-Geopackage</b>👍</p>This layer is stored in the Project-GeoPackage (a GeoPackage with the same name as the project file).<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    UNKNOWN = (
        lambda: ICONS.location_unknown,
        lambda: QCoreApplication.translate("LayerLocation", "<p>❓<b>Data Source Unknown</b>❓</p>The data source of this Layer could not be determined.<br><i>(Plugin: UTEC Layer Tools)</i>"),
    )
    # fmt: on

    def __init__(
        self, icon_factory: Callable[[], QIcon], tooltip_factory: Callable[[], str]
    ) -> None:
        """Initialize the enum member.

        Args:
            icon_factory: A callable that returns the icon associated with the layer location.
            tooltip_factory: A callable that returns the translated tooltip text.
        """
        self._icon_factory: Callable[[], QIcon] = icon_factory
        self._tooltip_factory: Callable[[], str] = tooltip_factory

    @property
    def icon(self) -> QIcon:
        """Return the icon for this location."""
        return self._icon_factory()

    @property
    def tooltip(self) -> str:
        """Generate and return the translated tooltip."""
        return self._tooltip_factory()
