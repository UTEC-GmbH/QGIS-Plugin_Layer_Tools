"""Module: general.py

This module contains the general functions.
"""

from typing import TYPE_CHECKING

from qgis.core import (
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

    :returns: A list of selected QgsMapLayer objects.
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

    :param layer: The layer whose attribute table should be cleared.
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
