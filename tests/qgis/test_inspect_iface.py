from qgis.gui import QgisInterface


def test_inspect_iface(qgis_iface: QgisInterface):
    print(f"\nIface class: {type(qgis_iface)}")
    print(f"Iface dir: {dir(qgis_iface)}")
    assert hasattr(qgis_iface, "layerTreeView")
