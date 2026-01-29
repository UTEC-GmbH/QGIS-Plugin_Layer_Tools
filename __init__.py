"""__init__.py

This script initializes the plugin, making it known to QGIS.
"""

# pylint: disable=invalid-name, import-outside-toplevel
# ruff: noqa: ANN001, ANN201, N802, PLC0415


def classFactory(iface):
    """Load the UTECLayerTools plugin class from the UTEC_layer_tools module.

    Args:
        iface: The QGIS interface instance.

    Returns:
        UTECLayerTools: An instance of the plugin class.
    """

    from .UTEC_layer_tools import UTECLayerTools

    return UTECLayerTools(iface)
