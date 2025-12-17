"""Module: layer_location.py

Determine the location of the layer's data source.
"""

import contextlib
import os
from typing import TYPE_CHECKING

from qgis.core import QgsLayerTree, QgsMapLayer, QgsProject, QgsVectorLayer
from qgis.gui import QgisInterface, QgsLayerTreeView, QgsLayerTreeViewIndicator
from qgis.PyQt.QtCore import QTimer

from .constants import LayerLocation
from .general import project_gpkg
from .logs_and_errors import log_debug

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


# TODO: Moving Layers within the layer tree (using drag-and-drop) leads to that layer losing its location indicator.
# TODO: When adding a layer from a geopackage, the location is identified correctly, but the indicator is not added.


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
        # map by layer id to avoid stale object-identity issues when the
        # layer-tree recreates nodes during moves/reorders
        self.location_indicators: dict[str, QgsLayerTreeViewIndicator] = {}
        self._model_reset_handler: Callable[[], None] | None = None
        self._rows_moved_handler: Callable[..., None] | None = None
        self._layout_changed_handler: Callable[[], None] | None = None

    def init_indicators(self) -> None:
        """Create initial indicators and connect signals."""
        self._update_all_location_indicators()
        self.iface.initializationCompleted.connect(self._on_project_read)
        self.project.layerWasAdded.connect(self._on_layer_added)
        self.project.layerWillBeRemoved.connect(self._on_layer_removed)

        if view := self.iface.layerTreeView():
            proxy_model = view.model()
            tree_model = view.layerTreeModel()

            # small delay to let layer-tree rebuild nodes on moves/reorders
            _delay_ms = 200

            # keep existing modelReset handler (connect to proxy and tree model)
            self._model_reset_handler = lambda: QTimer.singleShot(
                _delay_ms, self._on_layer_tree_model_reset
            )
            with contextlib.suppress(Exception):
                if proxy_model:
                    proxy_model.modelReset.connect(self._model_reset_handler)
            with contextlib.suppress(Exception):
                if tree_model:
                    tree_model.modelReset.connect(self._model_reset_handler)

            # catch drag/drop / move events and layout changes on both models
            self._rows_moved_handler = lambda *args: QTimer.singleShot(
                _delay_ms, self._on_layer_tree_model_reset
            )
            with contextlib.suppress(Exception):
                if proxy_model:
                    proxy_model.rowsMoved.connect(self._rows_moved_handler)
            with contextlib.suppress(Exception):
                if tree_model:
                    tree_model.rowsMoved.connect(self._rows_moved_handler)

            self._layout_changed_handler = lambda: QTimer.singleShot(
                _delay_ms, self._on_layer_tree_model_reset
            )
            with contextlib.suppress(Exception):
                if proxy_model:
                    proxy_model.layoutChanged.connect(self._layout_changed_handler)
            with contextlib.suppress(Exception):
                if tree_model:
                    tree_model.layoutChanged.connect(self._layout_changed_handler)

    def unload(self) -> None:
        """Clean up indicators and disconnect all signals."""
        self._clear_all_location_indicators()

        if view := self.iface.layerTreeView():
            proxy_model = view.model()
            tree_model = view.layerTreeModel()

            with contextlib.suppress(TypeError):
                if self._model_reset_handler and proxy_model:
                    proxy_model.modelReset.disconnect(self._model_reset_handler)
            with contextlib.suppress(TypeError):
                if self._model_reset_handler and tree_model:
                    tree_model.modelReset.disconnect(self._model_reset_handler)

            with contextlib.suppress(TypeError):
                if self._rows_moved_handler and proxy_model:
                    proxy_model.rowsMoved.disconnect(self._rows_moved_handler)
            with contextlib.suppress(TypeError):
                if self._rows_moved_handler and tree_model:
                    tree_model.rowsMoved.disconnect(self._rows_moved_handler)

            with contextlib.suppress(TypeError):
                if self._layout_changed_handler and proxy_model:
                    proxy_model.layoutChanged.disconnect(self._layout_changed_handler)
            with contextlib.suppress(TypeError):
                if self._layout_changed_handler and tree_model:
                    tree_model.layoutChanged.disconnect(self._layout_changed_handler)

        with contextlib.suppress(TypeError):
            self.iface.initializationCompleted.disconnect(self._on_project_read)
        with contextlib.suppress(TypeError):
            self.project.layerWasAdded.disconnect(self._on_layer_added)
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
            layer = self.project.mapLayer(layer_id)
            name = layer.name() if layer else layer_id
            log_debug(f"Location Indicators → '{name}' → indicator removed.")

        self.location_indicators.clear()
        log_debug("Location Indicators → Cleared all location indicators.")

    def _update_all_location_indicators(self) -> None:
        """Update location indicators for all layers in the project."""
        self._clear_all_location_indicators()
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not root:
            return
        for layer_node in root.findLayers():
            if layer_node and (map_layer := layer_node.layer()):
                self._add_indicator_for_layer(map_layer)

    def _remove_indicator_for_layer(self, layer: QgsMapLayer) -> None:
        """Remove the location indicator for a single layer."""
        view: QgsLayerTreeView | None = self.iface.layerTreeView()
        root: QgsLayerTree | None = self.project.layerTreeRoot()
        if not view or not root:
            return

        lid = layer.id()
        if lid in self.location_indicators:
            indicator = self.location_indicators[lid]
            if node := root.findLayer(lid):
                view.removeIndicator(node, indicator)
            del self.location_indicators[lid]
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
        lid = layer.id()
        if lid in self.location_indicators:
            log_debug(
                f"Location Indicators → '{layer.name()}' → indicator exists already."
            )
            return

        if indicator := add_location_indicator(self.project, self.iface, layer):
            self.location_indicators[lid] = indicator
            log_debug(
                f"Location Indicators → '{layer.name()}' → "
                "indicator added successfully."
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
        if self.project.isLoading():
            return

        log_debug(
            "Location Indicators → Layer tree reset detected, updating all indicators."
        )
        self._update_all_location_indicators()

    def _on_layer_added(self, layer: QgsMapLayer) -> None:
        """Handle the layerWasAdded signal."""
        log_debug(
            f"Location Indicators → '{layer.name()}' → Layer added, adding indicator..."
        )
        self._add_indicator_for_layer(layer)

    def _on_layer_removed(self, layer_id: str) -> None:
        """Handle the layerWillBeRemoved signal."""
        lid = layer_id
        if lid not in self.location_indicators:
            return

        # try to get the layer object (may already be gone)
        layer = self.project.mapLayer(lid)
        name = layer.name() if layer else lid
        log_debug(
            f"Location Indicators → '{name}' → Layer removed, removing indicator..."
        )

        if layer:
            self._disconnect_layer_signals(layer)
            self._remove_indicator_for_layer(layer)
        else:
            # layer object not available any more — remove stored indicator entry
            with contextlib.suppress(KeyError):
                self.location_indicators.pop(lid)
            log_debug(f"Location Indicators → '{name}' → indicator entry removed.")
