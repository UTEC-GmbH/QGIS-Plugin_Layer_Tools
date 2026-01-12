"""geopackage_indicators.py

This module contains functions for adding indicators to the QGIS file explorer.
"""

import contextlib
from typing import TYPE_CHECKING, Any

from qgis.core import QgsMapLayer, QgsProject
from qgis.gui import QgisInterface, QgsBrowserTreeView
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QIdentityProxyModel,
    QModelIndex,
    QObject,
    Qt,
    QTimer,
)

from .constants import ICONS
from .context import PluginContext
from .logs_and_errors import log_debug

if TYPE_CHECKING:
    from pathlib import Path

    from qgis.PyQt.QtGui import QIcon


class GeopackageProxyModel(QIdentityProxyModel):
    """Proxy model to override icons for the project GeoPackage and its tables."""

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the proxy model."""
        super().__init__(parent)
        self.project_gpkg_path: str = ""
        self.used_layers: set[str] = set()

        self.icon_gpkg_project: QIcon = ICONS.gpkg_project
        self.icon_used: QIcon = ICONS.gpkg_used
        self.icon_unused: QIcon = ICONS.gpkg_unused

    def update_project_data(self) -> None:
        """Update the internal state with current project data."""
        self.project_gpkg_path = ""
        project: QgsProject | None = QgsProject.instance()

        if project and project.fileName():
            with contextlib.suppress(RuntimeError, ValueError):
                path: Path = PluginContext.project_gpkg()
                self.project_gpkg_path = str(path).lower().replace("\\", "/")

        self.used_layers.clear()
        if not project:
            return

        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsMapLayer) or not layer.isValid():
                continue

            source: str = layer.source()
            norm_source: str = source.lower().replace("\\", "/")

            if self.project_gpkg_path and self.project_gpkg_path in norm_source:
                log_debug(
                    f"GeoPackage Indicators → Layer '{layer.name()}' "
                    "is used in the current project."
                )
                if "|layername=" in source:
                    parts: list[str] = source.split("|layername=")
                    if len(parts) > 1:
                        table_name: str = parts[1].split("|")[0]
                        self.used_layers.add(table_name)
                elif ":" in source:
                    # Raster or other → GPKG:/path/to.gpkg:tablename
                    parts = source.split(":")
                    if len(parts) >= 3:  # noqa: PLR2004
                        self.used_layers.add(parts[-1])

        # Trigger a refresh of the views
        self.layoutChanged.emit()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """Override data to provide custom icons."""

        if role == Qt.DecorationRole and index.isValid():
            item = index.internalPointer()

            if hasattr(item, "path"):
                item_path = item.path()
                norm_item_path: str = str(item_path).lower().replace("\\", "/")

                # Check for Project GPKG
                if self.project_gpkg_path and norm_item_path == self.project_gpkg_path:
                    return self.icon_gpkg_project

                # Check for Tables within Project GPKG
                if self.project_gpkg_path and norm_item_path.startswith(
                    self.project_gpkg_path
                ):
                    item_name = index.data(Qt.DisplayRole)
                    parent_index = index.parent()
                    if parent_index.isValid():
                        parent_item = parent_index.internalPointer()
                        if hasattr(parent_item, "path"):
                            parent_path: str = (
                                str(parent_item.path()).lower().replace("\\", "/")
                            )
                            if parent_path == self.project_gpkg_path:
                                return (
                                    self.icon_used
                                    if item_name in self.used_layers
                                    else self.icon_unused
                                )
        return super().data(index, role)


class GeopackageIndicatorManager:
    """Manages the insertion of the proxy model into QGIS Browser Docks."""

    def __init__(self, project: QgsProject, iface: QgisInterface) -> None:
        """Initialize the manager."""
        self.project: QgsProject = project
        self.iface: QgisInterface = iface
        self.proxies: list[GeopackageProxyModel] = []
        self._update_timer: QTimer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(200)

    def init_indicators(self) -> None:
        """Initialize indicators by wrapping browser models."""
        # Find all browser docks
        browser_views: list[QgsBrowserTreeView] = [
            widget
            for widget in QCoreApplication.instance().allWidgets()
            if isinstance(widget, QgsBrowserTreeView)
        ]

        if not browser_views:
            return

        for view in browser_views:
            original_model = view.model()

            if isinstance(original_model, GeopackageProxyModel):
                original_model.update_project_data()
                continue

            proxy = GeopackageProxyModel(view)
            proxy.setSourceModel(original_model)
            view.setModel(proxy)

            proxy.update_project_data()
            self.proxies.append(proxy)

        # Connect signals
        self._update_timer.timeout.connect(self._update_all_indicators)
        self.project.layersAdded.connect(self._on_layers_changed)
        self.project.layersRemoved.connect(self._on_layers_changed)
        self.iface.projectRead.connect(self._on_project_read)

    def _on_layers_changed(self, *args) -> None:  # noqa: ANN002, ARG002
        self._update_timer.start()

    def _on_project_read(self) -> None:
        self._update_all_indicators()

    def _update_all_indicators(self) -> None:
        log_debug("GeoPackage Indicators → Updating indicators...")
        for proxy in self.proxies:
            proxy.update_project_data()

    def unload(self) -> None:
        """Unload and restore original models."""
        if self._update_timer.isActive():
            self._update_timer.stop()

        with contextlib.suppress(TypeError, RuntimeError):
            self._update_timer.timeout.disconnect(self._update_all_indicators)

        with contextlib.suppress(TypeError, RuntimeError):
            self.project.layersAdded.disconnect(self._on_layers_changed)
            self.project.layersRemoved.disconnect(self._on_layers_changed)
            self.iface.projectRead.disconnect(self._on_project_read)

        for proxy in self.proxies:
            view = proxy.parent()
            if isinstance(view, QgsBrowserTreeView):
                source = proxy.sourceModel()
                view.setModel(source)

        self.proxies.clear()
