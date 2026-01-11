"""Module: general.py

This module contains the general functions.
"""

from typing import TYPE_CHECKING

from qgis.core import (
    QgsFeatureRequest,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMapLayer,
    QgsVectorDataProvider,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication

from .context import PluginContext
from .logs_and_errors import log_debug, raise_runtime_error, raise_user_error

if TYPE_CHECKING:
    from qgis.core import QgsDataProvider, QgsLayerTreeNode
    from qgis.gui import QgsLayerTreeView


def get_selected_layers() -> list[QgsMapLayer]:
    """Collect all layers selected in the QGIS layer tree view.

    Returns:
        list[QgsMapLayer]: A list of selected QgsMapLayer objects, sorted
        by their visual order in the layer tree.

    Raises:
        CustomRuntimeError: If QGIS interface or layer tree is unavailable.
        CustomUserError: If no layers or groups are selected.
    """
    # fmt: off
    # ruff: noqa: E501
    no_interface:str = QCoreApplication.translate("RuntimeError", "QGIS interface not set.")
    no_layertree:str = QCoreApplication.translate("RuntimeError", "Could not get layer tree view.")
    no_selection:str = QCoreApplication.translate("RuntimeError", "No layers or groups selected.")
    # fmt: on

    try:
        iface = PluginContext.iface()
    except RuntimeError:
        raise_runtime_error(no_interface)

    layer_tree: QgsLayerTreeView | None = iface.layerTreeView()
    if not layer_tree:
        raise_runtime_error(no_layertree)

    selected_layers: set[QgsMapLayer] = set()
    selected_nodes: list[QgsLayerTreeNode] = layer_tree.selectedNodes()
    if not selected_nodes:
        raise_user_error(no_selection)

    for node in selected_nodes:
        if isinstance(node, QgsLayerTreeGroup):
            # If a group is selected, add all its layers that are not empty recursively.
            for layer_node in node.findLayers():
                if layer := layer_node.layer():
                    selected_layers.add(layer)
        elif isinstance(node, QgsLayerTreeLayer) and node.layer():
            # Add the single selected layer.
            selected_layers.add(node.layer())
        else:
            log_debug(f"Unexpected node type in selection: {type(node)}")

    # Sort the selected layers based on their order in the layer tree (Top to Bottom)
    project = PluginContext.project()
    if project and (root := project.layerTreeRoot()):
        layer_order = root.layerOrder()

        # Create a mapping of layer ID to index for O(1) lookup
        order_map = {layer.id(): i for i, layer in enumerate(layer_order)}

        # Sort selected layers based on their index in the layer order
        # Layers not in the layer order (shouldn't happen for valid layers) will be at the end
        return sorted(
            selected_layers,
            key=lambda layer: order_map.get(layer.id(), float("inf")),
        )

    return list(selected_layers)


def clear_attribute_table(layer: QgsMapLayer) -> None:
    """Clear the attribute table of a QGIS layer by deleting all columns.

    Args:
        layer: The layer whose attribute table should be cleared.
    """
    if not isinstance(layer, QgsVectorLayer):
        # This function only applies to vector layers.
        return

    provider: QgsDataProvider | None = layer.dataProvider()
    if not provider:
        return

    # Check if the provider supports deleting attributes.
    if not provider.capabilities() & QgsVectorDataProvider.DeleteAttributes:
        return

    if field_indices := list(range(layer.fields().count())):
        provider.deleteAttributes(field_indices)
        layer.updateFields()


def is_empty_layer(layer: QgsMapLayer) -> bool:
    """Check if a vector layer is empty.

    This check is optimized to return as soon as the first feature is found,
    avoiding a full count of features which can be slow for large datasets.

    Args:
        layer: The layer to check.

    Returns:
        bool: True if the layer is a vector layer and has no features,
        False otherwise.
    """
    if not isinstance(layer, QgsVectorLayer):
        return False

    request = QgsFeatureRequest()
    request.setLimit(1)
    request.setFlags(QgsFeatureRequest.NoGeometry)
    return next(layer.getFeatures(request), None) is None
