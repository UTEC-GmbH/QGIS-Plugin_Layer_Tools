"""Module: layer_location.py

Determine the location of the layer's data source.
"""

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from qgis.core import (
    QgsLayerTree,
    QgsLayerTreeLayer,
    QgsLayerTreeModel,
    QgsLayerTreeNode,
    QgsMapLayer,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface, QgsLayerTreeView, QgsLayerTreeViewIndicator
from qgis.PyQt.QtCore import QCoreApplication, QTimer

from .constants import ICONS, LayerLocation
from .context import PluginContext
from .general import is_empty_layer
from .logs_and_errors import CustomUserError, log_debug

if TYPE_CHECKING:
    from collections.abc import Callable

LOG_PREFIX = "Location Indicators → "


def get_layer_source_path(layer: QgsMapLayer) -> str | None:
    """Extract the normalized source path of a layer.

    Args:
        layer: The QGIS map layer.

    Returns:
        str | None: The normalized source path or None if not applicable.
    """
    prov_instance: QgsProviderRegistry | None = QgsProviderRegistry.instance()
    if not prov_instance or layer.source().startswith("memory"):
        return None

    decoded_uri: dict = prov_instance.decodeUri(layer.providerType(), layer.source())

    # Use path from decoded URI if available, otherwise fall back to source
    uri_path: str = decoded_uri.get("path", "")
    if not uri_path:
        uri_path = layer.source().split("|")[0]
    return os.path.normcase(uri_path)


def is_cloud_layer(layer: QgsMapLayer, decoded_uri: dict | None = None) -> bool:
    """Check if a layer is from a cloud-based service.

    This function analyzes the layer's source string to determine if it
    originates from a web service (e.g., WMS, WFS) or a cloud database.

    Args:
        layer: The QGIS map layer to check.
        decoded_uri: Optional pre-decoded URI dictionary to avoid re-decoding.

    Returns:
        bool: True if the layer is identified as a cloud layer, False otherwise.
    """
    if decoded_uri is None:
        if prov_reg := QgsProviderRegistry.instance():
            decoded_uri = prov_reg.decodeUri(layer.providerType(), layer.source())
        else:
            return False
    source_lower: str = layer.source().lower()

    return (
        "url" in decoded_uri
        or "url=" in source_lower
        or source_lower.startswith(("http:", "https:"))
    )


def get_layer_location(layer: QgsMapLayer) -> LayerLocation | None:
    """Determine the location of the layer's data source.

    This function analyzes the layer's source string to classify its location
    relative to the QGIS project file. It can identify if a layer is stored in
    the project's associated GeoPackage, within the project folder, at an
    external file path, or from a cloud-based service. It also handles special
    cases like memory layers and empty vector layers.

    Args:
        layer: The QGIS map layer to check.

    Returns:
        LayerLocation | None: An enum member indicating the data source location,
        or None for memory layers.
    """
    project: QgsProject | None = QgsProject.instance()

    if (
        not QgsProviderRegistry.instance()
        or not project
        or not project.fileName()
        or layer.source().startswith("memory")
    ):
        return None

    if is_cloud_layer(layer):
        return LayerLocation.CLOUD

    try:
        project_gpkg_path: str = str(PluginContext.project_gpkg())
    except (CustomUserError, RuntimeError):
        return None

    # Use helper to get path
    layer_path: str = get_layer_source_path(layer) or ""

    gpkg: str = os.path.normcase(project_gpkg_path)
    project_folder: str = os.path.normcase(str(Path(project_gpkg_path).parent))

    if gpkg in layer_path:
        return LayerLocation.GPKG_PROJECT
    if project_folder in layer_path:
        return (
            LayerLocation.GPKG_FOLDER
            if layer_path.endswith((".gpkg", ".sqlite"))
            else LayerLocation.FOLDER_NO_GPKG
        )
    return LayerLocation.EXTERNAL


def _create_multi_indicator_tooltip(
    project: QgsProject, layer: QgsMapLayer, shared_names: list[str]
) -> str:
    """Build the HTML tooltip for a shared data source indicator.

    Args:
        project: The current QGIS project.
        layer: The layer to generate the tooltip for.
        shared_names: A list of other layer names sharing the source.

    Returns:
        The generated HTML tooltip as a string.
    """
    source_path_str: str | None = get_layer_source_path(layer)
    source_folder: str = ""
    source_file: str = ""
    source_layer_name: str = ""

    if source_path_str:
        source_path_obj: Path = Path(source_path_str)
        # Make relative to project if possible
        if project.fileName():
            with contextlib.suppress(ValueError):
                project_dir: Path = Path(project.fileName()).parent
                # Use os.path.relpath to handle drive letters on Windows
                relative_path: str = os.path.relpath(source_path_obj, project_dir)
                source_path_obj = Path(relative_path)

        source_folder = str(source_path_obj.parent)
        source_file = source_path_obj.name

    # Get layer/table name
    if prov_reg := QgsProviderRegistry.instance():
        decoded: dict = prov_reg.decodeUri(layer.providerType(), layer.source())
        if layer_name := decoded.get("layerName", ""):
            source_layer_name = layer_name
        elif "|layername=" in layer.source():
            with contextlib.suppress(IndexError):
                source_layer_name = layer.source().split("|layername=")[1].split("|")[0]

    # translations
    # fmt: off
    heading: str = QCoreApplication.translate("location_multi", "Shared Data Source")
    folder: str = QCoreApplication.translate("location_multi", "Folder")
    file: str = QCoreApplication.translate("location_multi", "File")
    layr: str = QCoreApplication.translate("location_multi", "Layer")
    used: str = QCoreApplication.translate("location_multi", "Used by:")
    # fmt: on

    # Build tooltip string with non-wrapping lines
    source_info_parts: list[str] = []
    span_style: str = 'style="white-space: nowrap;"'
    if source_folder and source_folder != ".":
        safe_folder: str = source_folder.replace(" ", "&nbsp;").replace("-", "&#8209;")
        source_info_parts.append(f"<span {span_style}>{folder}: '{safe_folder}'</span>")
    if source_file:
        safe_file: str = source_file.replace(" ", "&nbsp;").replace("-", "&#8209;")
        source_info_parts.append(f"<span {span_style}>{file}: '{safe_file}'</span>")
    if source_layer_name:
        safe_layer: str = source_layer_name.replace(" ", "&nbsp;").replace(
            "-", "&#8209;"
        )
        source_info_parts.append(f"<span {span_style}>{layr}: '{safe_layer}'</span>")

    source_info_html: str = ""
    if source_info_parts:
        source_info_html = "<p>" + "<br>".join(source_info_parts) + "</p>"

    names_list: str = "".join(
        f"<li><span {span_style}>{name}</span></li>" for name in shared_names
    )
    tooltip: str = (
        f"<p><b>{heading}</b></p>{source_info_html}<p>{used}<ul>{names_list}</ul></p>"
    )
    return tooltip


def _add_empty_indicator(
    layer: QgsMapLayer, view: QgsLayerTreeView, node: QgsLayerTreeNode
) -> QgsLayerTreeViewIndicator | None:
    """Add an 'empty' indicator if the layer has no features.

    Args:
        layer: The layer to check.
        view: The layer tree view to add the indicator to.
        node: The layer tree node corresponding to the layer.

    Returns:
        The created indicator, or None if the layer is not empty.
    """
    if not is_empty_layer(layer):
        return None

    indicator = QgsLayerTreeViewIndicator()
    indicator.setIcon(LayerLocation.EMPTY.icon)
    indicator.setToolTip(LayerLocation.EMPTY.tooltip)
    view.addIndicator(node, indicator)
    log_debug(
        f"'{layer.name()}' → adding empty indicator...",
        prefix=LOG_PREFIX,
        icon="🕳️",
    )
    return indicator


def _add_location_indicator(
    layer: QgsMapLayer, view: QgsLayerTreeView, node: QgsLayerTreeNode
) -> QgsLayerTreeViewIndicator | None:
    """Add a 'location' indicator based on the layer's data source.

    Args:
        layer: The layer to check.
        view: The layer tree view to add the indicator to.
        node: The layer tree node corresponding to the layer.

    Returns:
        The created indicator, or None if no location could be determined.
    """
    location: LayerLocation | None = get_layer_location(layer)
    if location is None:
        return None

    indicator = QgsLayerTreeViewIndicator()
    indicator.setIcon(location.icon)
    indicator.setToolTip(location.tooltip)
    view.addIndicator(node, indicator)
    log_debug(
        f"'{layer.name()}' → adding location indicator...",
        prefix=LOG_PREFIX,
        icon="📍",
    )
    return indicator


def _add_multi_indicator(
    project: QgsProject,
    layer: QgsMapLayer,
    view: QgsLayerTreeView,
    node: QgsLayerTreeNode,
    multi_info: tuple[int, list[str]] | None,
) -> QgsLayerTreeViewIndicator | None:
    """Add a 'multi' indicator if the layer shares its data source.

    Args:
        project: The current QGIS project.
        layer: The layer to add the indicator for.
        view: The layer tree view to add the indicator to.
        node: The layer tree node corresponding to the layer.
        multi_info: A tuple containing the icon index and list of shared names.

    Returns:
        The created indicator, or None if the layer does not have shared sources.
    """
    if not multi_info:
        return None

    idx, shared_names = multi_info
    indicator = QgsLayerTreeViewIndicator()
    indicator.setIcon(ICONS.get_multi_icon(idx))
    tooltip: str = _create_multi_indicator_tooltip(project, layer, shared_names)
    indicator.setToolTip(tooltip)
    view.addIndicator(node, indicator)
    log_debug(
        f"'{layer.name()}' → adding multi indicator...",
        prefix=LOG_PREFIX,
        icon="🔗",
    )
    return indicator


def add_location_indicator(
    layer: QgsMapLayer,
    multi_info: tuple[int, list[str]] | None = None,
) -> list[QgsLayerTreeViewIndicator] | None:
    """Add location indicators for a single layer to the layer tree view.

    This function orchestrates the addition of several types of indicators:
    - 'Empty' indicator if the layer has no features.
    - 'Location' indicator showing where the data is stored.
    - 'Multi' indicator if the data source is shared by other layers.

    Args:
        layer: The layer to add an indicator for.
        multi_info: Optional tuple of (icon_index, list_of_shared_layer_names).

    Returns:
        A list of added indicators, or None if no indicators were added.
    """
    project: QgsProject = PluginContext.project()
    iface: QgisInterface = PluginContext.iface()
    view: QgsLayerTreeView | None = iface.layerTreeView()
    root: QgsLayerTree | None = project.layerTreeRoot()

    if not view or not root:
        return None

    node: QgsLayerTreeNode | None = root.findLayer(layer.id())
    if not node:
        return None

    indicators: list[QgsLayerTreeViewIndicator] = []

    if indicator := _add_empty_indicator(layer, view, node):
        indicators.append(indicator)

    if indicator := _add_location_indicator(layer, view, node):
        indicators.append(indicator)

    if indicator := _add_multi_indicator(project, layer, view, node, multi_info):
        indicators.append(indicator)

    return indicators or None


class LocationIndicatorManager:
    """Manages location indicators for layers in the QGIS layer tree."""

    def __init__(self, project: QgsProject, iface: QgisInterface) -> None:
        """Initialize the manager.

        Args:
            project: The current QGIS project instance.
            iface: The QGIS interface instance.
        """
        self.project: QgsProject = project
        self.iface: QgisInterface = iface
        self.location_indicators: dict[str, list[QgsLayerTreeViewIndicator]] = {}
        # Cache stores (LocationType, TreeNodeObject, MultiInfo)
        self.layer_locations: dict[
            str, tuple[LayerLocation | None, QgsLayerTreeNode | None, tuple | None]
        ] = {}
        self.shared_groups: dict[str, tuple[int, list[str]]] = {}
        self._model_reset_handler: Callable[[], None] | None = None
        self._tree_change_handler: Callable[..., None] | None = None
        self._layout_changed_handler: Callable[[], None] | None = None
        self._rows_moved_handler: Callable[..., None] | None = None
        self._rows_removed_handler: Callable[..., None] | None = None
        self._rows_inserted_handler: Callable[..., None] | None = None
        self._update_timer: QTimer = QTimer()

    def init_indicators(self) -> None:
        """Create initial indicators and connect signals.

        Sets up the signal connections for layer tree changes and initialization,
        and triggers an initial update of all indicators.
        """
        self._update_all_location_indicators()
        self.iface.initializationCompleted.connect(self._on_project_read)
        self.project.layerWillBeRemoved.connect(self._on_layer_removed)

        # Configure debounce timer
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(200)
        self._update_timer.timeout.connect(self._on_layer_tree_model_reset)

        if view := self.iface.layerTreeView():
            proxy_model = view.model()
            tree_model: QgsLayerTreeModel | None = view.layerTreeModel()

            # Combined handler for all tree changes - restarts timer (debounce)
            self._tree_change_handler = lambda *_: self._update_timer.start()

            # keep existing modelReset handler (connect to proxy and tree model)
            self._model_reset_handler = self._tree_change_handler
            with contextlib.suppress(Exception):
                if proxy_model:
                    proxy_model.modelReset.connect(self._model_reset_handler)
            with contextlib.suppress(Exception):
                if tree_model:
                    tree_model.modelReset.connect(self._model_reset_handler)

            # catch drag/drop / move events on both models
            # We treat Insert/Move safely by just requesting an update
            self._rows_moved_handler = self._tree_change_handler
            self._rows_inserted_handler = self._tree_change_handler
            self._rows_removed_handler = self._tree_change_handler

            for model in [proxy_model, tree_model]:
                if model:
                    with contextlib.suppress(Exception):
                        model.rowsMoved.connect(self._rows_moved_handler)
                        model.rowsInserted.connect(self._rows_inserted_handler)
                        model.rowsRemoved.connect(self._rows_removed_handler)

            self._layout_changed_handler = self._tree_change_handler
            with contextlib.suppress(Exception):
                if proxy_model:
                    proxy_model.layoutChanged.connect(self._layout_changed_handler)
            with contextlib.suppress(Exception):
                if tree_model:
                    tree_model.layoutChanged.connect(self._layout_changed_handler)

    def unload(self) -> None:
        """Clean up indicators and disconnect all signals.

        Removes all indicators from the layer tree and disconnects all connected
        signals to ensure a clean unload.
        """
        self._clear_all_location_indicators()

        if self._update_timer.isActive():
            self._update_timer.stop()
        with contextlib.suppress(TypeError, RuntimeError):
            self._update_timer.timeout.disconnect(self._on_layer_tree_model_reset)

        if view := self.iface.layerTreeView():
            models: list = [view.model(), view.layerTreeModel()]
            definitions: list[tuple[str, str]] = [
                ("_model_reset_handler", "modelReset"),
                ("_rows_moved_handler", "rowsMoved"),
                ("_rows_inserted_handler", "rowsInserted"),
                ("_rows_removed_handler", "rowsRemoved"),
                ("_layout_changed_handler", "layoutChanged"),
            ]

            for handler_name, signal_name in definitions:
                handler: str | None = getattr(self, handler_name, None)
                if not handler:
                    continue

                for model in models:
                    if not model:
                        continue
                    with contextlib.suppress(TypeError):
                        getattr(model, signal_name).disconnect(handler)

        with contextlib.suppress(TypeError):
            self.iface.initializationCompleted.disconnect(self._on_project_read)

        with contextlib.suppress(TypeError):
            self.project.layerWillBeRemoved.disconnect(self._on_layer_removed)

        for layer in self.project.mapLayers().values():
            self._disconnect_layer_signals(layer)

    def _clear_all_location_indicators(self) -> None:
        """Remove all location indicators from the layer tree view."""
        view: QgsLayerTreeView | None = self.iface.layerTreeView()
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not view or not root or not self.location_indicators:
            return

        for layer_id, indicators in list(self.location_indicators.items()):
            if node := root.findLayer(layer_id):
                for indicator in indicators:
                    view.removeIndicator(node, indicator)

        self.location_indicators.clear()
        self.layer_locations.clear()
        log_debug("Cleared all location indicators.", prefix=LOG_PREFIX, icon="🧹")

    def _update_all_location_indicators(self) -> None:
        """Update location indicators for all layers in the project using diffs."""
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not root:
            return

        visible_layer_ids: set[str] = self._get_visible_layer_ids(root)
        self._calculate_shared_groups(visible_layer_ids)
        self._update_indicators_for_visible_layers(visible_layer_ids)
        self._cleanup_removed_layers(visible_layer_ids)

    def _get_visible_layer_ids(self, root: QgsLayerTree) -> set[str]:
        """Collect all layer IDs currently visible in the layer tree."""
        visible_layer_ids: set = set()
        for layer_node in root.findLayers():
            if layer_node and (layer := layer_node.layer()):
                visible_layer_ids.add(layer.id())
        return visible_layer_ids

    def _calculate_shared_groups(self, visible_layer_ids: set[str]) -> None:
        """Calculate groups of layers sharing the same source."""
        self.shared_groups.clear()
        # Key is (normalized_path, layer_name)
        source_map: dict[tuple[str, str], list[QgsMapLayer]] = {}

        for lid in visible_layer_ids:
            if (
                (prov_registry := QgsProviderRegistry.instance())
                and (layer := self.project.mapLayer(lid))
                and (path := get_layer_source_path(layer))
            ):
                # Extract sub-layer name (table name)
                decoded = prov_registry.decodeUri(layer.providerType(), layer.source())

                if is_cloud_layer(layer, decoded_uri=decoded):
                    continue

                layer_name = decoded.get("layerName", "")

                if not layer_name and "|layername=" in layer.source():
                    with contextlib.suppress(IndexError):
                        layer_name = (
                            layer.source().split("|layername=")[1].split("|")[0]
                        )

                source_map.setdefault((path, layer_name), []).append(layer)

        # Sort groups by source path to ensure deterministic icon assignment
        sorted_sources = sorted(
            (key, layers) for key, layers in source_map.items() if len(layers) > 1
        )

        for icon_idx, (_, layers) in enumerate(sorted_sources):
            layer_names: list[str] = sorted(layer.name() for layer in layers)
            for layer in layers:
                self.shared_groups[layer.id()] = (icon_idx, layer_names)

    def _update_indicators_for_visible_layers(
        self, visible_layer_ids: set[str]
    ) -> None:
        """Update indicators for all visible layers, adding or removing as needed."""
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not root:
            return

        for lid in visible_layer_ids:
            if not (layer := self.project.mapLayer(lid)):
                continue

            layer_node: QgsLayerTreeLayer | None = root.findLayer(lid)

            new_location: LayerLocation | None = get_layer_location(layer)
            multi_info: tuple[int, list[str]] | None = self.shared_groups.get(lid)

            # Check if we already have this state
            cached_state: (
                tuple[LayerLocation | None, QgsLayerTreeNode | None, tuple | None]
                | None
            ) = self.layer_locations.get(lid)

            cached_location: LayerLocation | None = (
                cached_state[0] if cached_state else None
            )
            cached_node: QgsLayerTreeNode | None = (
                cached_state[1] if cached_state else None
            )
            cached_multi: tuple | None = (
                cached_state[2] if cached_state and len(cached_state) > 2 else None  # noqa: PLR2004
            )

            # If state matches, skip update
            if (
                new_location == cached_location
                and layer_node == cached_node
                and multi_info == cached_multi
                and (lid in self.location_indicators or new_location is None)
            ):
                continue

            # State changed or new layer/node
            if lid in self.location_indicators:
                self._remove_indicator_for_layer(layer)

            if new_location or is_empty_layer(layer):
                # _add_indicator_for_layer will update the cache with new node
                self._add_indicator_for_layer(layer)
            else:
                # Update cache for None location (and potentially None multi_info)
                self.layer_locations[lid] = (None, layer_node, multi_info)

    def _cleanup_removed_layers(self, visible_layer_ids: set[str]) -> None:
        """Remove indicators for layers no longer in the tree.

        (This handles cases where a layer was hidden/removed
        but signal didn't catch it
        or we want to be strictly consistent with the current tree traversal)
        """
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not root:
            return

        for lid in list(self.location_indicators.keys()):
            if lid not in visible_layer_ids:
                if layer := self.project.mapLayer(lid):
                    self._remove_indicator_for_layer(layer)
                else:
                    self._cleanup_deleted_layer(root, lid)

    def _cleanup_deleted_layer(self, root: QgsLayerTree, lid: str) -> None:
        """Clean up indicator entry for a layer that was deleted."""
        if (view := self.iface.layerTreeView()) and (node := root.findLayer(lid)):
            with contextlib.suppress(KeyError):
                for indicator in self.location_indicators[lid]:
                    view.removeIndicator(node, indicator)

        with contextlib.suppress(KeyError):
            del self.location_indicators[lid]
            del self.layer_locations[lid]

    def _remove_indicator_for_layer(self, layer: QgsMapLayer) -> None:
        """Remove the location indicators for a single layer."""
        view: QgsLayerTreeView | None = self.iface.layerTreeView()
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not view or not root:
            return

        lid = layer.id()
        if lid in self.location_indicators:
            indicators: list[QgsLayerTreeViewIndicator] = self.location_indicators[lid]
            if node := root.findLayer(lid):
                for indicator in indicators:
                    view.removeIndicator(node, indicator)
            del self.location_indicators[lid]
            if lid in self.layer_locations:
                del self.layer_locations[lid]
            log_debug(
                f"'{layer.name()}' → indicators removed.", prefix=LOG_PREFIX, icon="🧹"
            )

    def _update_indicator_for_layer(self, layer_id: str) -> None:
        """Add or update a location indicator for a single layer."""
        layer: QgsMapLayer | None = self.project.mapLayer(layer_id)
        if not layer:
            return

        log_debug(
            f"'{layer.name()}' → updating indicator...", prefix=LOG_PREFIX, icon="♻️"
        )
        self._remove_indicator_for_layer(layer)
        self._add_indicator_for_layer(layer)

        if (
            (view := self.iface.layerTreeView())
            and (model := view.layerTreeModel())
            and (root := self.project.layerTreeRoot())
            and (node := root.findLayer(layer.id()))
        ):
            model_index = model.node2index(node)
            model.dataChanged.emit(model_index, model_index)

    def _layer_location_cache(
        self, indicators: list[QgsLayerTreeViewIndicator], lid: str, layer: QgsMapLayer
    ) -> None:
        """Cache indicators and layer location state."""
        self.location_indicators[lid] = indicators

        # Find the node to cache it
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        node: QgsLayerTreeLayer | None = root.findLayer(lid) if root else None

        self.layer_locations[lid] = (
            get_layer_location(layer),
            node,
            self.shared_groups.get(lid),
        )

        self._connect_layer_signals(layer)

    def _add_indicator_for_layer(self, layer: QgsMapLayer) -> None:
        """Add location and empty indicators for a single layer if they don't exist."""
        layer_id: str = layer.id()
        if layer_id in self.location_indicators:
            return

        multi_info = self.shared_groups.get(layer_id)

        if indicators := add_location_indicator(layer, multi_info):
            self._layer_location_cache(indicators, layer_id, layer)

    def _connect_layer_signals(self, layer: QgsMapLayer) -> None:
        """Connect signals for a specific layer."""
        if isinstance(layer, QgsVectorLayer):
            with contextlib.suppress(TypeError):
                layer.editingStopped.connect(
                    lambda: self._on_layer_modified(layer.id())
                )

    def _disconnect_layer_signals(self, layer: QgsMapLayer) -> None:
        """Disconnect signals from a specific layer."""
        if isinstance(layer, QgsVectorLayer):
            with contextlib.suppress(TypeError, RuntimeError):
                # Disconnect all signals from this layer for this receiver
                layer.editingStopped.disconnect()

    def _on_layer_modified(self, layer_id: str) -> None:
        """Handle modification of a layer (e.g., after saving edits)."""
        layer: QgsMapLayer | None = self.project.mapLayer(layer_id)
        if not layer:
            return

        log_debug(
            f"'{layer.name()}' → Layer modified, queueing indicator update...",
            prefix=LOG_PREFIX,
            icon="♻️",
        )
        QTimer.singleShot(0, lambda: self._update_indicator_for_layer(layer_id))

    def _on_project_read(self) -> None:
        """Handle the projectRead signal after a project is loaded."""
        log_debug(
            "Project loaded, setting up all indicators and signals.",
            prefix=LOG_PREFIX,
            icon="🚀",
        )
        self._update_all_location_indicators()

    def _on_layer_tree_model_reset(self) -> None:
        """Handle the layer tree model's reset signal, e.g., on reorder."""

        log_debug(
            "Layer tree reset detected, updating all indicators.",
            prefix=LOG_PREFIX,
            icon="♻️",
        )
        self._update_all_location_indicators()

    def _on_layer_removed(self, layer_id: str) -> None:
        """Handle the layerWillBeRemoved signal."""

        if layer_id not in self.location_indicators:
            return

        if layer := self.project.mapLayer(layer_id):
            self._disconnect_layer_signals(layer)
            self._remove_indicator_for_layer(layer)
        else:
            # layer object not available any more — remove stored indicator entry
            with contextlib.suppress(KeyError):
                self.location_indicators.pop(layer_id)
