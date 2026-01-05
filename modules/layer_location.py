"""Module: layer_location.py

Determine the location of the layer's data source.
"""

import contextlib
import os
from typing import TYPE_CHECKING

from qgis.core import (
    QgsLayerTree,
    QgsLayerTreeLayer,
    QgsLayerTreeModel,
    QgsLayerTreeNode,
    QgsMapLayer,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface, QgsLayerTreeView, QgsLayerTreeViewIndicator
from qgis.PyQt.QtCore import QTimer

from .constants import LayerLocation
from .general import project_gpkg
from .logs_and_errors import log_debug

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def get_layer_location(layer: QgsMapLayer) -> LayerLocation | None:
    """Determine the location of the layer's data source.

    This function analyzes the layer's source string to classify its location
    relative to the QGIS project file. It can identify if a layer is stored in
    the project's associated GeoPackage, within the project folder, at an
    external file path, or from a cloud-based service. It also handles special
    cases like memory layers and empty vector layers.

    Args:
        layer (QgsMapLayer): The QGIS map layer to check.

    Returns:
        LayerLocation | None: An enum member indicating the data source location,
        or None for memory layers.
    """
    location: LayerLocation | None = None
    log_message: str = ""

    layer_source: str = os.path.normcase(layer.source())
    gpkg_path: Path = project_gpkg()
    gpkg: str = os.path.normcase(str(gpkg_path))
    project_folder: str = os.path.normcase(str(gpkg_path.parent))

    if isinstance(layer, QgsVectorLayer) and layer.featureCount() == 0:
        location = LayerLocation.EMPTY
        log_message = "Layer is empty."
    elif layer_source.startswith("memory"):
        # Memory layers get an indicator from QGIS itself, so we return None.
        location = None
        log_message = "memory layer (no indicator needed)"
    elif "url=" in layer_source:
        location = LayerLocation.CLOUD
        log_message = "cloud data source. ☁️"
    elif gpkg in layer_source:
        location = LayerLocation.GPKG_PROJECT
        log_message = "in project GeoPackage. ✅"
    elif project_folder in layer_source:
        if ".gpkg" in layer_source:
            location = LayerLocation.GPKG_FOLDER
            log_message = "in a different GeoPackage in the project folder. ✔️"
        else:
            location = LayerLocation.FOLDER_NO_GPKG
            log_message = "in the project folder, but not in a GeoPackage. ⚠️"
    else:
        location = LayerLocation.EXTERNAL
        log_message = "💥 external data source 💥"

    log_debug(f"Location Indicators → '{layer.name()}' → Layer location: {log_message}")
    return location


def add_location_indicator(
    project: QgsProject, iface: QgisInterface, layer: QgsMapLayer
) -> QgsLayerTreeViewIndicator | None:
    """Add a location indicator for a single layer to the layer tree view."""

    location: LayerLocation | None = get_layer_location(layer)
    if location is None:
        return None

    indicator = QgsLayerTreeViewIndicator()
    indicator.setIcon(location.icon)
    indicator.setToolTip(location.tooltip)
    if (
        project
        and (view := iface.layerTreeView())
        and (root := project.layerTreeRoot())
        and (node := root.findLayer(layer.id()))
    ):
        view.addIndicator(node, indicator)
        log_debug(f"Location Indicators → '{layer.name()}' → adding indicator...")
        return indicator

    return None


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
        self.location_indicators: dict[str, QgsLayerTreeViewIndicator] = {}
        # Cache stores (LocationType, TreeNodeObject) to detect node recreation
        self.layer_locations: dict[
            str, tuple[LayerLocation | None, QgsLayerTreeNode | None]
        ] = {}
        self._model_reset_handler: Callable[[], None] | None = None
        self._tree_change_handler: Callable[..., None] | None = None
        self._layout_changed_handler: Callable[[], None] | None = None
        self._rows_moved_handler: Callable[..., None] | None = None
        self._rows_removed_handler: Callable[..., None] | None = None
        self._rows_inserted_handler: Callable[..., None] | None = None
        self._update_timer: QTimer = QTimer()

    def init_indicators(self) -> None:
        """Create initial indicators and connect signals."""
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
        """Clean up indicators and disconnect all signals."""
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
                handler = getattr(self, handler_name, None)
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

        for layer_id, indicator in list(self.location_indicators.items()):
            if node := root.findLayer(layer_id):
                view.removeIndicator(node, indicator)
            # attempt to get layer name for logging
            layer: QgsMapLayer | None = self.project.mapLayer(layer_id)
            name: str = layer.name() if layer else layer_id
            log_debug(f"Location Indicators → '{name}' → indicator removed.")

        self.location_indicators.clear()
        self.layer_locations.clear()
        log_debug("Location Indicators → Cleared all location indicators.")

    def _update_all_location_indicators(self) -> None:
        """Update location indicators for all layers in the project using diffs."""
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not root:
            return

        visible_layer_ids: set[str] = self._get_visible_layer_ids(root)
        self._update_indicators_for_visible_layers(visible_layer_ids)
        self._cleanup_removed_layers(visible_layer_ids)

    def _get_visible_layer_ids(self, root: QgsLayerTree) -> set[str]:
        """Collect all layer IDs currently visible in the layer tree."""
        visible_layer_ids: set = set()
        for layer_node in root.findLayers():
            if layer_node and (layer := layer_node.layer()):
                visible_layer_ids.add(layer.id())
        return visible_layer_ids

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
            # Check if we already have this state (Location AND Node identity)
            cached_state: (
                tuple[LayerLocation | None, QgsLayerTreeNode | None] | None
            ) = self.layer_locations.get(lid)
            cached_location: LayerLocation | None = (
                cached_state[0] if cached_state else None
            )
            cached_node: QgsLayerTreeNode | None = (
                cached_state[1] if cached_state else None
            )

            # If location type matches AND it's the same tree node object, skip update
            if (
                new_location == cached_location
                and layer_node == cached_node
                and (lid in self.location_indicators or new_location is None)
            ):
                continue

            # State changed or new layer/node
            if lid in self.location_indicators:
                self._remove_indicator_for_layer(layer)

            if new_location:
                # _add_indicator_for_layer will update the cache with new node
                self._add_indicator_for_layer(layer)
            else:
                # Update cache for None location
                self.layer_locations[lid] = (None, layer_node)

    def _cleanup_removed_layers(self, visible_layer_ids: set[str]) -> None:
        """Remove indicators for layers no longer in the tree."""
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not root:
            return

        # Cleanup: Remove indicators for layers no longer in the tree
        # (This handles cases where a layer was hidden/removed
        # but signal didn't catch it
        # or we want to be strictly consistent with the current tree traversal)
        for lid in list(self.location_indicators.keys()):
            if lid not in visible_layer_ids:
                # Need layer object to remove safely?
                if layer := self.project.mapLayer(lid):
                    self._remove_indicator_for_layer(layer)
                else:
                    self._cleanup_deleted_layer(root, lid)

    def _cleanup_deleted_layer(self, root: QgsLayerTree, lid: str) -> None:
        """Clean up indicator entry for a layer that was deleted."""
        if (view := self.iface.layerTreeView()) and (node := root.findLayer(lid)):
            with contextlib.suppress(KeyError):
                view.removeIndicator(node, self.location_indicators[lid])

        with contextlib.suppress(KeyError):
            del self.location_indicators[lid]
            del self.layer_locations[lid]

    def _remove_indicator_for_layer(self, layer: QgsMapLayer) -> None:
        """Remove the location indicator for a single layer."""
        view: QgsLayerTreeView | None = self.iface.layerTreeView()
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not view or not root:
            return

        lid = layer.id()
        if lid in self.location_indicators:
            indicator: QgsLayerTreeViewIndicator = self.location_indicators[lid]
            if node := root.findLayer(lid):
                view.removeIndicator(node, indicator)
            del self.location_indicators[lid]
            if lid in self.layer_locations:
                del self.layer_locations[lid]
            log_debug(f"Location Indicators → '{layer.name()}' → indicator removed.")

    def _update_indicator_for_layer(self, layer_id: str) -> None:
        """Add or update a location indicator for a single layer."""
        layer: QgsMapLayer | None = self.project.mapLayer(layer_id)
        if not layer:
            return

        log_debug(f"Location Indicators → '{layer.name()}' → updating indicator...")
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

    def _add_indicator_for_layer(self, layer: QgsMapLayer) -> None:
        """Add a location indicator for a single layer if it doesn't exist."""
        layer_id: str = layer.id()
        if layer_id in self.location_indicators:
            log_debug(
                f"Location Indicators → '{layer.name()}' → indicator exists already."
            )
            return

        if indicator := add_location_indicator(self.project, self.iface, layer):
            self._layer_location_cache(indicator, layer_id, layer)

    def _layer_location_cache(
        self, indicator: QgsLayerTreeViewIndicator, lid: str, layer: QgsMapLayer
    ) -> None:
        self.location_indicators[lid] = indicator

        # Find the node to cache it
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        node: QgsLayerTreeLayer | None = root.findLayer(lid) if root else None

        self.layer_locations[lid] = (get_layer_location(layer), node)
        log_debug(
            f"Location Indicators → '{layer.name()}' → indicator added successfully."
        )
        self._connect_layer_signals(layer)

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
            f"Location Indicators → '{layer.name()}' → "
            "Layer modified, queueing indicator update..."
        )
        QTimer.singleShot(0, lambda: self._update_indicator_for_layer(layer_id))

    def _on_project_read(self) -> None:
        """Handle the projectRead signal after a project is loaded."""
        log_debug(
            "Location Indicators → Project loaded, "
            "setting up all indicators and signals."
        )
        self._update_all_location_indicators()

    def _on_layer_tree_model_reset(self) -> None:
        """Handle the layer tree model's reset signal, e.g., on reorder."""

        log_debug(
            "Location Indicators → Layer tree reset detected, updating all indicators."
        )
        self._update_all_location_indicators()

    def _on_layer_removed(self, layer_id: str) -> None:
        """Handle the layerWillBeRemoved signal."""

        if layer_id not in self.location_indicators:
            return

        # try to get the layer object (may already be gone)
        layer: QgsMapLayer | None = self.project.mapLayer(layer_id)
        name: str = layer.name() if layer else layer_id
        log_debug(
            f"Location Indicators → '{name}' → Layer removed, removing indicator..."
        )

        if layer:
            self._disconnect_layer_signals(layer)
            self._remove_indicator_for_layer(layer)
        else:
            # layer object not available any more — remove stored indicator entry
            with contextlib.suppress(KeyError):
                self.location_indicators.pop(layer_id)
            log_debug(f"Location Indicators → '{name}' → indicator entry removed.")
