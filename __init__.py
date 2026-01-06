"""__init__.py

This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name  # noqa: ANN001, ANN201, N802
    """Load the UTECLayerTools plugin class from the UTEC_layer_tools module.

    Args:
        iface: The QGIS interface instance.

    Returns:
        UTECLayerTools: An instance of the plugin class.
    """
    # pylint: disable=import-outside-toplevel
    from .UTEC_layer_tools import UTECLayerTools  # noqa: PLC0415

    return UTECLayerTools(iface)
