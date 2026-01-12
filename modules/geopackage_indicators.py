"""geopackage_indicators.py

This module contains functions for adding indicators to the QGIS file explorer.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsLayerItem,
    QgsMapLayer,
    QgsProject,
    QgsProviderRegistry,
)
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

    from qgis.core import QgsProviderSublayerDetails
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

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        """Override data to provide custom icons."""
        if role != Qt.DecorationRole or not index.isValid():
            return super().data(index, role)

        if not self.project_gpkg_path:
            return super().data(index, role)

        source_index = self.mapToSource(index)
        item = self.sourceModel().data(source_index, Qt.UserRole)

        if not isinstance(item, QgsDataItem):
            return super().data(index, role)

        item_path = item.path()
        norm_item_path: str = str(item_path).lower().replace("\\", "/")

        # Check for Project GPKG
        if norm_item_path == self.project_gpkg_path:
            return self.icon_gpkg_project

        # Check for Tables within Project GPKG
        if norm_item_path.startswith(self.project_gpkg_path):
            parent_source_index = source_index.parent()
            if parent_source_index.isValid():
                parent_item = self.sourceModel().data(parent_source_index, Qt.UserRole)
                if isinstance(parent_item, QgsDataItem):
                    parent_path: str = (
                        str(parent_item.path()).lower().replace("\\", "/")
                    )
                    if parent_path == self.project_gpkg_path:
                        item_name = self.sourceModel().data(
                            source_index, Qt.DisplayRole
                        )
                        return (
                            self.icon_used
                            if item_name in self.used_layers
                            else self.icon_unused
                        )

        return super().data(index, role)


class ProjectGpkgDataItem(QgsDataCollectionItem):
    # pylint: disable=too-few-public-methods
    """Data item representing the project's GeoPackage."""

    def __init__(self, parent: QgsDataItem | None, path: str, gpkg_path: Path) -> None:
        """Initialize the item."""
        super().__init__(parent, "Project GeoPackage", path, "Project GeoPackage")
        self.gpkg_path: Path = gpkg_path
        self.setIcon(ICONS.gpkg_project)

    def createChildren(self) -> list[QgsDataItem]:  # noqa: N802
        """Create children items (layers) from the GeoPackage."""
        children: list[QgsDataItem] = []
        if not self.gpkg_path.exists():
            return children

        # Query sublayers to get details efficiently
        registry: QgsProviderRegistry | None = QgsProviderRegistry.instance()
        if not registry:
            return children

        sublayers: list[QgsProviderSublayerDetails] = registry.querySublayers(
            str(self.gpkg_path)
        )

        for sub in sublayers:
            layer_type = QgsLayerItem.LayerType.NoType
            if sub.type() == Qgis.LayerType.Vector:
                layer_type = QgsLayerItem.LayerType.Vector
            elif sub.type() == Qgis.LayerType.Raster:
                layer_type = QgsLayerItem.LayerType.Raster

            item = QgsLayerItem(
                self,
                sub.name(),
                sub.uri(),
                sub.uri(),
                layer_type,
                sub.providerKey(),
            )
            children.append(item)
        return children


class ProjectGpkgDataItemProvider(QgsDataItemProvider):
    """Provider to add the Project GeoPackage to the browser tree."""

    def name(self) -> str:
        """Return the provider name."""
        return "Project GeoPackage"

    def capabilities(self) -> Qgis.DataItemProviderCapabilities:
        """Return the provider capabilities."""
        return Qgis.DataItemProviderCapabilities(
            Qgis.DataItemProviderCapability.NoCapabilities
        )

    def createDataItem(  # noqa: N802
        self,
        path: str | None,
        parentItem: QgsDataItem | None,  # noqa: N803
    ) -> QgsDataItem | None:
        """Create a data item for the given path."""
        if path:
            return None

        # Root item request
        with contextlib.suppress(Exception):
            gpkg_path: Path = PluginContext.project_gpkg()
            if gpkg_path.exists():
                return ProjectGpkgDataItem(parentItem, "project_gpkg", gpkg_path)
        return None


class GeopackageIndicatorManager:
    """Manages the insertion of the proxy model into QGIS Browser Docks."""

    def __init__(self, project: QgsProject, iface: QgisInterface) -> None:
        """Initialize the manager."""
        self.project: QgsProject = project
        self.iface: QgisInterface = iface
        self.proxies: list[GeopackageProxyModel] = []
        self.provider: ProjectGpkgDataItemProvider | None = None
        self._update_timer: QTimer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(200)

    def init_indicators(self) -> None:
        """Initialize indicators by wrapping browser models."""
        # Register Data Item Provider
        self.provider = ProjectGpkgDataItemProvider()
        if registry := QgsApplication.dataItemProviderRegistry():
            registry.addProvider(self.provider)

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

    def _on_layers_changed(self) -> None:
        self._update_timer.start()

    def _on_project_read(self) -> None:
        self._update_all_indicators()
        # Reload browser to update Project GeoPackage item
        self.iface.reloadConnections()

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

        if self.provider:
            if registry := QgsApplication.dataItemProviderRegistry():
                registry.removeProvider(self.provider)
            self.provider = None

        for proxy in self.proxies:
            view = proxy.parent()
            if isinstance(view, QgsBrowserTreeView):
                source = proxy.sourceModel()
                view.setModel(source)

        self.proxies.clear()
