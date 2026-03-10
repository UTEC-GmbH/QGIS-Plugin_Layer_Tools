import os
import sys
from pathlib import Path

# Add project root to sys.path
root = Path(r"c:\Users\fl\Documents\Python\QGIS-Plugin_Layer_Tools")
sys.path.insert(0, str(root))

from unittest.mock import MagicMock

# Adjust _OSGEO4W_ROOT if OSGeo4W is installed elsewhere.
_OSGEO4W_ROOT = os.environ.get("OSGEO4W_ROOT", r"C:\OSGeo4W")
_DLL_DIRS = [
    rf"{_OSGEO4W_ROOT}\bin",
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr\bin",
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr-qt6\bin",
    rf"{_OSGEO4W_ROOT}\apps\Qt5\bin",
    rf"{_OSGEO4W_ROOT}\apps\Qt6\bin",
]
if os.name == "nt":
    for _dll_dir in _DLL_DIRS:
        if os.path.isdir(_dll_dir):
            os.add_dll_directory(_dll_dir)

from qgis.core import Qgis, QgsApplication
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QT_VERSION_STR

# Initialize QGIS
qgs = QgsApplication([], False)
qgs.initQgis()

print(f"QGIS Version: {Qgis.version()}")
print(f"Qt Version: {QT_VERSION_STR}")

from modules.browser import GeopackageProxyModel
from modules.context import PluginContext

# Mock iface
iface = MagicMock(spec=QgisInterface)
PluginContext.init(iface, root)

try:
    print("Testing GeopackageProxyModel initialization...")
    model = GeopackageProxyModel()
    print(f"model.icon_gpkg: {model.icon_gpkg}")

    print("Testing _create_composite_icon...")
    icon = model._create_composite_icon(model.icon_gpkg, model.icon_used)
    print(f"composite icon: {icon}")

    if icon is None:
        print("ERROR: icon is None!")
    else:
        print(f"SUCCESS: icon is {type(icon)}")

finally:
    qgs.exitQgis()
