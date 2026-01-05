"""__init__.py

This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load MoveLayersToGPKG class from file MoveLayersToGPKG.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .UTEC_layer_tools import UTECLayerTools

    return UTECLayerTools(iface)
