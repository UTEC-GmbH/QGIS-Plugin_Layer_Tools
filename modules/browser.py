"""Module: browser.py

This module contains functions for customising the QGIS browser (file explorer).
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
    QgsDataItemProviderRegistry,
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
from .logs_and_errors import CustomUserError, log_debug

if TYPE_CHECKING:
    from pathlib import Path

    from qgis.PyQt.QtGui import QIcon

LOG_PREFIX: str = "Browser → "


class GeopackageProxyModel(QIdentityProxyModel):
    """Proxy model to override icons for the project GeoPackage and its tables."""

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the proxy model."""
        super().__init__(parent)
        log_debug("GeopackageProxyModel initialized.", icon="🐞", prefix=LOG_PREFIX)
        self.project_gpkg_path: str = ""
        self.used_layers: set[str] = set()

        self.icon_gpkg: QIcon = ICONS.browser_gpkg
        self.icon_used: QIcon = ICONS.browser_used
        self.icon_unused: QIcon = ICONS.browser_unused

    def update_project_data(self) -> None:
        """Update the internal state with current project data."""
        log_debug(
            "GeopackageProxyModel.update_project_data called.",
            icon="🐞",
            prefix=LOG_PREFIX,
        )
        self.project_gpkg_path = ""
        project: QgsProject | None = QgsProject.instance()

        if project and project.fileName():
            with contextlib.suppress(CustomUserError, RuntimeError, ValueError):
                path: Path = PluginContext.project_gpkg()
                self.project_gpkg_path = str(path).lower().replace("\\", "/")
                log_debug(
                    f"Project GPKG path set to: {self.project_gpkg_path}",
                    icon="🐞",
                    prefix=LOG_PREFIX,
                )

        self.used_layers.clear()
        if not project:
            log_debug(
                "GeopackageProxyModel.update_project_data: No project.",
                icon="🐞",
                prefix=LOG_PREFIX,
            )
            return

        reg: QgsProviderRegistry | None = QgsProviderRegistry.instance()
        if not reg:
            return

        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsMapLayer) or not layer.isValid():
                log_debug(
                    f"GeopackageProxyModel.update_project_data: "
                    f"Layer '{layer.name()}' is not valid.",
                    icon="🐞",
                    prefix=LOG_PREFIX,
                )
                continue

            # Use decodeUri for robust path extraction
            decoded_uri: dict = reg.decodeUri(layer.providerType(), layer.source())
            uri_path = decoded_uri.get("path", layer.source())
            norm_source: str = str(uri_path).lower().replace("\\", "/")

            if self.project_gpkg_path and self.project_gpkg_path == norm_source:
                log_debug(
                    f"Layer '{layer.name()}' is used in the current project.",
                    icon="🔗",
                    prefix=LOG_PREFIX,
                )
                # Try to get table name from decoded URI or source
                table_name: str = decoded_uri.get("layerName", "")
                if not table_name and "|layername=" in layer.source():
                    parts: list[str] = layer.source().split("|layername=")
                    if len(parts) > 1:
                        table_name = parts[1].split("|")[0]
                elif not table_name and ":" in layer.source():
                    parts = layer.source().split(":")
                    if len(parts) >= 3:  # noqa: PLR2004
                        table_name = parts[-1]

                if table_name:
                    self.used_layers.add(table_name)

        # Trigger a refresh of the views
        log_debug(
            "GeopackageProxyModel.update_project_data: refreshing views.",
            icon="🐞",
            prefix=LOG_PREFIX,
        )
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

        # Check for Project GPKG (Custom Item)
        if norm_item_path == "project_gpkg:":
            log_debug(
                f"Icon override for Project GPKG Item: {norm_item_path}",
                icon="🐞",
                prefix=LOG_PREFIX,
            )
            return self.icon_gpkg

        # Check for Project GPKG
        if norm_item_path == self.project_gpkg_path:
            log_debug(
                f"Icon override for Project GPKG: {norm_item_path}",
                icon="🐞",
                prefix=LOG_PREFIX,
            )
            return self.icon_gpkg

        # Check for tables within the project GeoPackage (either our custom
        # item or the standard file system item)
        parent_source_index = source_index.parent()
        if parent_source_index.isValid():
            parent_item = self.sourceModel().data(parent_source_index, Qt.UserRole)
            if isinstance(parent_item, QgsDataItem):
                parent_path: str = str(parent_item.path()).lower().replace("\\", "/")
                is_child_of_gpkg_file = parent_path == self.project_gpkg_path
                is_child_of_custom_item = parent_path.startswith("project_gpkg:")

                if is_child_of_gpkg_file or is_child_of_custom_item:
                    item_name = self.sourceModel().data(source_index, Qt.DisplayRole)
                    log_debug(
                        f"Icon override for layer: {item_name}",
                        icon="🐞",
                        prefix=LOG_PREFIX,
                    )
                    return (
                        self.icon_used
                        if item_name in self.used_layers
                        else self.icon_unused
                    )

        return super().data(index, role)


# pylint: disable=too-few-public-methods
class ProjectGpkgDataItem(QgsDataCollectionItem):
    """Data item representing the project's GeoPackage."""

    def __init__(self, parent: QgsDataItem | None, path: str, gpkg_path: Path) -> None:
        """Initialize the item."""
        super().__init__(
            parent,
            QCoreApplication.translate("Browser", "UTEC Project GeoPackage"),
            path,
            "UTEC Project GeoPackage",
        )
        self.gpkg_path: Path = gpkg_path
        self.setIcon(ICONS.browser_gpkg)

    def sortKey(self) -> object:  # noqa: N802
        """Return a sort key to position this item after Project Home."""
        return " 1"

    def createChildren(self) -> list[QgsDataItem]:  # noqa: N802
        """Create children items (layers) from the GeoPackage.

        This method delegates the creation of child items to the native data
        provider (usually OGR). It creates a temporary file item for the
        GeoPackage and extracts its children (the layers). This ensures that
        the items have the correct native behavior (icons, fields, etc.).
        """
        children: list[QgsDataItem] = []
        if not self.gpkg_path.exists():
            return children

        registry: QgsDataItemProviderRegistry | None = (
            QgsApplication.dataItemProviderRegistry()
        )
        if not registry:
            return children

        # Iterate over all available providers to find one that can handle the
        # GeoPackage and produce children (layers).
        for provider in registry.providers():
            # Skip our own provider to avoid recursion or confusion
            if provider.name() == "UTEC Project GeoPackage":
                continue

            try:
                # Create a temporary item representing the GeoPackage file itself.
                # We pass None as parent because we only need it to generate children.
                file_item: QgsDataItem | None = provider.createDataItem(
                    str(self.gpkg_path), None
                )

                if file_item:
                    # Generate the children (layers) using the native item's logic.
                    native_children: list[QgsDataItem] = file_item.createChildren()

                    if native_children:
                        for item in native_children:
                            item.setParent(self)
                            children.append(item)
                        return children
            except Exception:  # noqa: BLE001
                continue

        return children


class ProjectGpkgDataItemProvider(QgsDataItemProvider):
    """Provider to add the Project GeoPackage to the browser tree."""

    def __init__(self, gpkg_path: Path) -> None:
        """Initialize the provider."""
        super().__init__()
        self._gpkg_path: Path = gpkg_path
        log_debug(
            f"ProjectGpkgDataItemProvider initialized for {gpkg_path}",
            icon="🐞",
            prefix=LOG_PREFIX,
        )

    def __del__(self) -> None:
        """Log destruction."""
        log_debug(
            "ProjectGpkgDataItemProvider destroyed.", icon="💀", prefix=LOG_PREFIX
        )

    def name(self) -> str:
        """Return the provider name."""
        return "UTEC Project GeoPackage"

    def capabilities(self) -> Qgis.DataItemProviderCapabilities:
        """Return the provider capabilities."""
        log_debug(
            "ProjectGpkgDataItemProvider.capabilities called.",
            prefix=LOG_PREFIX,
            icon="🐞",
        )
        return Qgis.DataItemProviderCapabilities(
            Qgis.DataItemProviderCapability.Database
        )

    def createDataItem(  # noqa: N802
        self,
        path: str | None,
        parentItem: QgsDataItem | None,  # noqa: N803
    ) -> QgsDataItem | None:
        """Create a data item for the given path."""
        try:
            log_debug(f"createDataItem called with path='{path}'", prefix=LOG_PREFIX)

            # QGIS calls this with path="" (empty string) for the root item.
            if (not path or path == "project_gpkg:") and self._gpkg_path.exists():
                log_debug(
                    f"ProjectGpkgDataItemProvider: Creating item for {self._gpkg_path}",
                    icon="💫",
                    prefix=LOG_PREFIX,
                )
                # We use a colon suffix to ensure the path is treated as absolute/unique
                return ProjectGpkgDataItem(parentItem, "project_gpkg:", self._gpkg_path)

            return None

        except Exception as e:
            log_debug(f"Error in createDataItem: {e}", icon="💀", prefix=LOG_PREFIX)
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
        self._current_gpkg_path: str | None = None

    def init_indicators(self) -> None:
        """Initialize indicators by wrapping browser models."""
        log_debug(
            "GeopackageIndicatorManager.init_indicators called.",
            icon="🐞",
            prefix=LOG_PREFIX,
        )

        # Connect signals
        self._update_timer.timeout.connect(self._update_all_indicators)
        self.project.layersAdded.connect(self._on_layers_changed)
        self.project.layersRemoved.connect(self._on_layers_changed)
        self.iface.projectRead.connect(self._on_project_read)
        self.iface.initializationCompleted.connect(self._install_proxies)

        self._update_all_indicators()
        # Try installing immediately (in case of plugin reload)
        self._install_proxies()

    def _install_proxies(self) -> None:
        """Find browser views and install proxies."""
        browser_views: list[QgsBrowserTreeView] = [
            widget
            for widget in QCoreApplication.instance().allWidgets()
            if isinstance(widget, QgsBrowserTreeView)
        ]
        log_debug(
            f"Found {len(browser_views)} browser views.", icon="🐞", prefix=LOG_PREFIX
        )

        for view in browser_views:
            original_model = view.model()
            log_debug(
                f"Processing view with model: {type(original_model)}",
                icon="🐞",
                prefix=LOG_PREFIX,
            )

            if original_model is None:
                continue

            if isinstance(original_model, GeopackageProxyModel):
                original_model.update_project_data()
                continue

            log_debug(
                f"Installing proxy on view with model: {original_model}",
                prefix=LOG_PREFIX,
                icon="🐞",
            )
            proxy = GeopackageProxyModel(view)
            proxy.setSourceModel(original_model)
            view.setModel(proxy)
            log_debug("Proxy model installed on view.", icon="🐞", prefix=LOG_PREFIX)

            proxy.update_project_data()
            self.proxies.append(proxy)

    def _on_layers_changed(self) -> None:
        self._update_timer.start()

    def _on_project_read(self) -> None:
        self._update_all_indicators()
        # Reload browser to update Project GeoPackage item
        self.iface.reloadConnections()

    def _update_all_indicators(self) -> None:
        log_debug("Updating indicators...", prefix=LOG_PREFIX, icon="♻️")

        # Update provider path
        gpkg_path: Path | None = None

        # Check if project is saved to avoid UserError from PluginContext
        project = QgsProject.instance()
        if project and project.fileName():
            with contextlib.suppress(Exception):
                gpkg_path = PluginContext.project_gpkg()

        # Only use path if it exists
        if gpkg_path and not gpkg_path.exists():
            gpkg_path = None

        new_path_str = str(gpkg_path) if gpkg_path else None

        if new_path_str != self._current_gpkg_path:
            self._current_gpkg_path = new_path_str

            # Remove existing provider
            if self.provider:
                if registry := QgsApplication.dataItemProviderRegistry():
                    registry.removeProvider(self.provider)
                self.provider = None

            # Add new provider if we have a valid path
            if gpkg_path:
                self.provider = ProjectGpkgDataItemProvider(gpkg_path)
                if registry := QgsApplication.dataItemProviderRegistry():
                    registry.addProvider(self.provider)

            log_debug("Reloading browser connections...", prefix=LOG_PREFIX)
            self.iface.reloadConnections()

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
            self.iface.initializationCompleted.disconnect(self._install_proxies)

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
