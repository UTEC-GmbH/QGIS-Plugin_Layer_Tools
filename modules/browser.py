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
    QgsLayerItem,
    QgsMapLayer,
    QgsMimeDataUtils,
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
from qgis.PyQt.QtGui import QIcon, QImage, QPainter, QPixmap

from .constants import ICONS
from .context import PluginContext
from .logs_and_errors import CustomUserError, log_debug

if TYPE_CHECKING:
    from pathlib import Path

LOG_PREFIX: str = "Browser → "


class GeopackageProxyModel(QIdentityProxyModel):
    """Proxy model to override icons for the project GeoPackage and its tables."""

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the proxy model.

        Args:
            parent: The parent object.
        """
        super().__init__(parent)
        self.project_gpkg_path: str = ""
        self.used_layers: set[str] = set()

        self.icon_gpkg: QIcon = ICONS.browser_gpkg
        self.icon_used: QIcon = ICONS.browser_used
        self.icon_unused: QIcon = ICONS.browser_unused
        self._icon_cache: dict[str, QIcon] = {}

    def _create_composite_icon(self, base_icon: QIcon, overlay_icon: QIcon) -> QIcon:
        """Create a composite icon with an overlay.

        Args:
            base_icon: The base icon.
            overlay_icon: The icon to overlay on the base icon.

        Returns:
            QIcon: The composite icon.
        """
        size = 32

        # Use QImage for software rendering - safer than QPixmap in some contexts
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        try:
            base_pixmap = base_icon.pixmap(size, size)
            if not base_pixmap.isNull():
                painter.drawPixmap(0, 0, base_pixmap)

            # Draw overlay icon
            overlay_size = 24
            overlay_pixmap = overlay_icon.pixmap(overlay_size, overlay_size)

            if not overlay_pixmap.isNull():
                x: int = size - overlay_size
                y: int = size - overlay_size
                painter.drawPixmap(x, y, overlay_pixmap)

        finally:
            painter.end()

        return QIcon(QPixmap.fromImage(image))

    def update_project_data(self) -> None:
        """Update the internal state with current project data.

        This method refreshes the list of used layers and the project GeoPackage path.
        """

        reg: QgsProviderRegistry | None = QgsProviderRegistry.instance()
        if not reg:
            log_debug("No provider registry found.", Qgis.Critical, prefix=LOG_PREFIX)
            return

        project: QgsProject | None = QgsProject.instance()
        if not project:
            log_debug("No project found.", Qgis.Critical, prefix=LOG_PREFIX)
            return

        self.project_gpkg_path = ""
        if project and project.fileName():
            with contextlib.suppress(CustomUserError, RuntimeError, ValueError):
                path: Path = PluginContext.project_gpkg()
                self.project_gpkg_path = str(path).lower().replace("\\", "/")

        self.used_layers.clear()
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsMapLayer) or not layer.isValid():
                continue

            decoded_uri: dict = reg.decodeUri(layer.providerType(), layer.source())
            uri_path = decoded_uri.get("path", layer.source())
            norm_source: str = str(uri_path).lower().replace("\\", "/")

            if self.project_gpkg_path and self.project_gpkg_path == norm_source:
                log_debug(
                    f"Layer '{layer.name()}' is used in the current project.",
                    icon="⭐",
                    prefix=LOG_PREFIX,
                )
                if table_name := self._get_table_name(
                    layer.source(), layer.providerType()
                ):
                    self.used_layers.add(table_name)

        # Trigger a refresh of the views
        self.layoutChanged.emit()

    def _get_table_name(self, uri: str, provider: str = "ogr") -> str:
        """Extract table name from layer URI consistently.

        Args:
            uri: The layer URI.
            provider: The provider key (default: "ogr").

        Returns:
            str: The extracted table name or an empty string.
        """
        reg: QgsProviderRegistry | None = QgsProviderRegistry.instance()
        if not reg:
            return ""

        decoded_uri: dict = reg.decodeUri(provider, uri)
        table_name: str = decoded_uri.get("layerName", "")

        if not table_name and "|layername=" in uri:
            parts: list[str] = uri.split("|layername=")
            if len(parts) > 1:
                table_name = parts[1].split("|")[0]
        elif not table_name and ":" in uri:
            parts = uri.split(":")
            if len(parts) >= 3:  # noqa: PLR2004
                table_name = parts[-1]

        return table_name

    def _get_custom_icon(
        self, index: QModelIndex, item: QgsDataItem | str, item_path: str
    ) -> QIcon:
        """Determine and return the custom icon for a layer item.

        Args:
            index: The model index of the item.
            item: The data item or string representation.
            item_path: The path of the item.

        Returns:
            QIcon: The custom icon indicating usage status.
        """

        is_used: bool = False
        table_name: str = ""

        if isinstance(item, QgsLayerItem):
            table_name = self._get_table_name(item.uri(), item.providerKey())
        else:
            # Fallback for strings (path) or generic QgsDataItem
            # Try to extract table name from URI/Path
            # Usually: /path/to.gpkg|layername=my_table
            uri: str = item_path
            table_name = self._get_table_name(uri, "ogr")

        if table_name:
            is_used = table_name in self.used_layers
        else:
            # Fallback to display name (least reliable)
            # Use super().data() because 'index' is a Proxy Index
            item_name = super().data(index, Qt.ItemDataRole.DisplayRole)
            is_used = item_name in self.used_layers

        # Get the original icon (DecorationRole)
        base_icon_variant = super().data(index, Qt.ItemDataRole.DecorationRole)
        base_icon = (
            base_icon_variant if isinstance(base_icon_variant, QIcon) else QIcon()
        )

        if base_icon.isNull() and isinstance(item, QgsDataItem):
            base_icon = item.icon()

        status_icon = self.icon_used if is_used else self.icon_unused

        # Create cache key
        # Include base_icon cache key to handle icon updates (e.g. generic -> specific)
        base_key = base_icon.cacheKey()
        cache_key: str = f"{item_path}_{is_used}_{base_key}"
        if cache_key not in self._icon_cache:
            self._icon_cache[cache_key] = self._create_composite_icon(
                base_icon, status_icon
            )

        return self._icon_cache[cache_key]

    def _get_item_from_index(self, index: QModelIndex) -> QgsDataItem | str | None:
        """Retrieve the data item or path string from a model index.

        Args:
            index: The model index.

        Returns:
            QgsDataItem | str | None: The data item, its path string, or None.
        """
        model = self.sourceModel()
        if hasattr(model, "dataItem") and (item := model.dataItem(index)):
            return item
        return model.data(index, Qt.ItemDataRole.UserRole)

    def _get_raw_path(self, item: QgsDataItem | str | None) -> str:
        """Extract the raw path from a data item.

        Args:
            item: The data item or path string.

        Returns:
            str: The raw path string.
        """
        if isinstance(item, QgsDataItem):
            return item.path()
        return item if isinstance(item, str) else ""

    def _get_normalized_path(self, item: QgsDataItem | str | None) -> str:
        """Extract and normalize the path from a data item.

        Args:
            item: The data item or path string.

        Returns:
            str: The normalized path string (lowercase, forward slashes).
        """
        raw_path: str = self._get_raw_path(item)
        return raw_path.lower().replace("\\", "/") if raw_path else ""

    def _is_gpkg_child(self, source_index: QModelIndex) -> bool:
        """Check if the item at source_index is a child of the project GeoPackage.

        Args:
            source_index: The source model index.

        Returns:
            bool: True if the item is a child of the project GeoPackage,
                False otherwise.
        """
        parent_index = source_index.parent()
        if not parent_index.isValid():
            return False

        parent_item: QgsDataItem | str | None = self._get_item_from_index(parent_index)
        parent_path: str = self._get_normalized_path(parent_item)

        return parent_path == self.project_gpkg_path or parent_path.startswith(
            "project_gpkg:"
        )

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        """Override data to provide custom icons.

        Args:
            index: The model index.
            role: The data role.

        Returns:
            object: The data for the given role.
        """
        if (
            role != Qt.ItemDataRole.DecorationRole
            or not index.isValid()
            or not self.project_gpkg_path
        ):
            return super().data(index, role)

        source_index = self.mapToSource(index)
        item: QgsDataItem | str | None = self._get_item_from_index(source_index)
        raw_path: str = self._get_raw_path(item)

        if not raw_path:
            return super().data(index, role)

        # Check for tables within the project GeoPackage FIRST
        try:
            if self._is_gpkg_child(source_index):
                with contextlib.suppress(Exception):
                    return self._get_custom_icon(index, item, raw_path)
        except Exception as e:  # noqa: BLE001, pylint: disable=broad-except
            log_debug(f"Error in data(): {e}", Qgis.Critical, prefix=LOG_PREFIX)

        # If not a child layer, check if it is the GPKG file itself
        norm_path: str = raw_path.lower().replace("\\", "/")
        if norm_path in ("project_gpkg:", self.project_gpkg_path):
            return self.icon_gpkg

        return super().data(index, role)


class WrappedProjectLayerItem(QgsLayerItem):
    """Wrapper around a native layer item to ensure unique paths."""

    def __init__(self, parent: QgsDataItem, native_item: QgsDataItem) -> None:
        """Initialize the wrapper.

        Args:
            parent: The parent data item.
            native_item: The native data item to wrap.
        """
        # Determine URI safely
        path: str = (
            native_item.uri() if hasattr(native_item, "uri") else native_item.path()
        )
        name: str = native_item.name()
        uri: str = path
        provider_key: str = (
            native_item.providerKey() if hasattr(native_item, "providerKey") else "ogr"
        )

        browser_layer_type = (
            native_item.layerType()
            if hasattr(native_item, "layerType")
            else Qgis.BrowserLayerType.Vector
        )

        # Initialize as a Layer type
        super().__init__(parent, name, path, uri, browser_layer_type, provider_key)

        self._native_item: QgsDataItem = native_item

        # Set the icon immediately
        if hasattr(native_item, "icon") and not native_item.icon().isNull():
            self.setIcon(native_item.icon())

    def hasChildren(self) -> bool:  # noqa: N802
        """Delegate hasChildren to native item.

        Returns:
            bool: True if the item has children, False otherwise.
        """
        return self._native_item.hasChildren()

    def createChildren(self) -> list[QgsDataItem]:  # noqa: N802
        """Delegate createChildren to native item.

        Returns:
            list[QgsDataItem]: The list of child items.
        """
        return self._native_item.createChildren()

    def mimeUri(self) -> QgsMimeDataUtils.Uri:  # noqa: N802
        """Delegate mimeUri to native item for Drag&Drop.

        Returns:
            QgsMimeDataUtils.Uri: The MIME URI of the item.
        """
        return self._native_item.mimeUri()

    def capabilities2(self) -> Qgis.BrowserItemCapabilities:
        """Delegate capabilities to native item (crucial for Drag&Drop).

        Returns:
            Qgis.BrowserItemCapabilities: The capabilities of the item.
        """
        return self._native_item.capabilities2()

    def capabilities(self):  # noqa: ANN201
        """Delegate legacy capabilities.

        Returns:
            The legacy capabilities of the item.
        """
        return self._native_item.capabilities()

    def flags(self):  # noqa: ANN201
        """Delegate flags (essential for Drag&Drop).

        Returns:
            The flags of the item.
        """
        return self._native_item.flags()


class ProjectGpkgDataItem(QgsDataCollectionItem):
    """Data item representing the project's GeoPackage."""

    def __init__(self, parent: QgsDataItem | None, path: str, gpkg_path: Path) -> None:
        """Initialize the item.

        Args:
            parent: The parent data item.
            path: The path of the item.
            gpkg_path: The path to the GeoPackage file.
        """
        super().__init__(
            parent,
            QCoreApplication.translate("Browser", "UTEC Project GeoPackage"),
            path,
            "UTEC Project GeoPackage",
        )
        self.gpkg_path: Path = gpkg_path
        self.setIcon(ICONS.browser_gpkg)
        self._provider_item: QgsDataItem | None = None

    def sortKey(self) -> object:  # noqa: N802
        """Return a sort key to position this item after Project Home.

        Returns:
            object: The sort key.
        """
        return " 1"

    def _wrap_item(self, item: QgsDataItem) -> WrappedProjectLayerItem | None:
        """Safely wrap a native data item.

        Args:
            item: The native data item to wrap.

        Returns:
            WrappedProjectLayerItem | None: The wrapped item or None if wrapping failed.
        """
        try:
            return WrappedProjectLayerItem(self, item)
        except Exception as e:  # noqa: BLE001, pylint: disable=broad-except
            log_debug(
                f"Failed to wrap native item '{item.name()}': {e}",
                Qgis.Critical,
                prefix=LOG_PREFIX,
            )
            return None

    def createChildren(self) -> list[QgsDataItem]:  # noqa: N802
        """Create children items (layers) from the GeoPackage.

        This method delegates the creation of child items to the native data
        provider (usually OGR). It creates a temporary file item for the
        GeoPackage and extracts its children (the layers). This ensures that
        the items have the correct native behavior (icons, fields, etc.).

        Returns:
            list[QgsDataItem]: A list of wrapped child data items.
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
                if (
                    file_item := provider.createDataItem(str(self.gpkg_path), None)
                ) and (native_children := file_item.createChildren()):
                    # Keep a reference to the provider item
                    # to prevent GC/Connection closing
                    self._provider_item = file_item

                    return [
                        wrapped
                        for item in native_children
                        if (wrapped := self._wrap_item(item))
                    ]

            except Exception as e:  # pylint: disable=broad-except  # noqa: BLE001
                log_debug(
                    f"Error creating children for {self.gpkg_path}: {e}",
                    Qgis.Warning,
                    prefix=LOG_PREFIX,
                )
                continue

        return children


class ProjectGpkgDataItemProvider(QgsDataItemProvider):
    """Provider to add the Project GeoPackage to the browser tree."""

    def __init__(self, gpkg_path: Path) -> None:
        """Initialize the provider.

        Args:
            gpkg_path: The path to the project GeoPackage.
        """
        super().__init__()
        self._gpkg_path: Path = gpkg_path

    def name(self) -> str:
        """Return the provider name.

        Returns:
            str: The provider name.
        """
        return "UTEC Project GeoPackage"

    def capabilities(self) -> Qgis.DataItemProviderCapabilities:
        """Return the provider capabilities.

        Returns:
            Qgis.DataItemProviderCapabilities: The provider capabilities.
        """
        return Qgis.DataItemProviderCapabilities(
            Qgis.DataItemProviderCapability.Database
        )

    def createDataItem(  # noqa: N802
        self,
        path: str | None,
        parentItem: QgsDataItem | None,  # noqa: N803
    ) -> QgsDataItem | None:
        """Create a data item for the given path.

        Args:
            path: The path for the data item.
            parentItem: The parent data item.

        Returns:
            QgsDataItem | None: The created data item or None.
        """
        try:
            # QGIS calls this with path="" (empty string) for the root item.
            if (not path or path == "project_gpkg:") and self._gpkg_path.exists():
                # We use a colon suffix to ensure the path is treated as absolute/unique
                return ProjectGpkgDataItem(parentItem, "project_gpkg:", self._gpkg_path)

            return None  # noqa: TRY300

        except Exception as e:  # noqa: BLE001, pylint: disable=broad-except
            log_debug(f"Error in createDataItem: {e}", Qgis.Critical, prefix=LOG_PREFIX)
            return None


class GeopackageIndicatorManager:
    """Manages the insertion of the proxy model into QGIS Browser Docks."""

    def __init__(self, project: QgsProject, iface: QgisInterface) -> None:
        """Initialize the manager.

        Args:
            project: The QGIS project instance.
            iface: The QGIS interface instance.
        """
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

        for view in browser_views:
            original_model = view.model()
            if original_model is None:
                continue

            if isinstance(original_model, GeopackageProxyModel):
                original_model.update_project_data()
                continue

            proxy = GeopackageProxyModel(view)
            proxy.setSourceModel(original_model)
            view.setModel(proxy)

            proxy.update_project_data()
            self.proxies.append(proxy)

    def _on_layers_changed(self) -> None:
        """Handle layer addition or removal events."""
        self._update_timer.start()

    def _on_project_read(self) -> None:
        """Handle project read event."""
        self._update_all_indicators()
        # Reload browser to update Project GeoPackage item
        self.iface.reloadConnections()

    def _update_all_indicators(self) -> None:
        """Update all indicators and the project GeoPackage provider."""
        log_debug("Updating indicators...", prefix=LOG_PREFIX, icon="♻️")

        # Ensure we are hooked into all available browser views
        # (Some might have initialized late)
        self._install_proxies()

        # Update provider path
        gpkg_path: Path | None = None

        # Check if project is saved to avoid UserError from PluginContext
        project: QgsProject | None = QgsProject.instance()
        if project and project.fileName():
            with contextlib.suppress(Exception):
                gpkg_path = PluginContext.project_gpkg()

        # Only use path if it exists
        if gpkg_path and not gpkg_path.exists():
            gpkg_path = None

        new_path_str: str | None = str(gpkg_path) if gpkg_path else None

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

            log_debug("Reloading browser connections...", prefix=LOG_PREFIX, icon="♻️")
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
