"""Shared pytest fixtures for the UTEC Layer Tools test suite.

Windows / OSGeo4W DLL bootstrapping
-------------------------------------
QGIS needs native DLLs (GDAL, PROJ, Qt, ...) in OSGeo4W bin directories.
When pytest is launched from VS Code or a plain terminal (not the OSGeo4W
Shell), those dirs are absent from PATH.  We register them here with
``os.add_dll_directory`` *before* any QGIS import so the linker finds them
regardless of how pytest was started.  Silently skips dirs that don't exist,
so this file is safe on non-Windows/CI machines.

Fixtures
---------
- ``init_plugin_context`` — session-scoped autouse fixture that initialises
  ``PluginContext`` with the stubbed ``qgis_iface`` from pytest-qgis.
- ``plugin_dir`` — path to the plugin root directory.
- ``tmp_gpkg`` — a fresh ``.gpkg`` path inside pytest's ``tmp_path``.
- ``memory_point_layer`` — empty in-memory Point layer.
- ``memory_line_layer`` — empty in-memory LineString layer.
- ``clean_project`` — a ``QgsProject`` wiped clean for each test.
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# DLL / sys.path bootstrapping (Windows only)
# ---------------------------------------------------------------------------
# Adjust _OSGEO4W_ROOT if OSGeo4W is installed elsewhere.
_OSGEO4W_ROOT: str = os.environ.get("OSGEO4W_ROOT", r"C:\OSGeo4W")

_DLL_DIRS: list[str] = [
    rf"{_OSGEO4W_ROOT}\bin",
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr\bin",
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr-qt6\bin",
    rf"{_OSGEO4W_ROOT}\apps\Qt5\bin",
    rf"{_OSGEO4W_ROOT}\apps\Qt6\bin",
]
_SITE_DIRS: list[str] = [
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr\python",
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr\python\plugins",
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr-qt6\python",
    rf"{_OSGEO4W_ROOT}\apps\qgis-ltr-qt6\python\plugins",
    rf"{_OSGEO4W_ROOT}\apps\Python312\Lib\site-packages",
]

if os.name == "nt":  # Windows only
    for _dll_dir in _DLL_DIRS:
        if os.path.isdir(_dll_dir):
            os.add_dll_directory(_dll_dir)  # type: ignore[attr-defined]
    for _site_dir in _SITE_DIRS:
        if os.path.isdir(_site_dir) and _site_dir not in sys.path:
            sys.path.insert(0, _site_dir)

# ---------------------------------------------------------------------------
# Now it is safe to import from qgis.*
# ---------------------------------------------------------------------------
import pytest
from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgisInterface

# ---------------------------------------------------------------------------
# PluginContext initialisation
# ---------------------------------------------------------------------------
# ``qgis_iface`` is a session-scoped fixture provided by pytest-qgis.
# We wire it into PluginContext once per session so all modules that call
# PluginContext.iface() / .project() resolve correctly.


@pytest.fixture(scope="session", autouse=True)
def init_plugin_context(qgis_iface: QgisInterface) -> None:
    """Initialise PluginContext with the pytest-qgis stub interface.

    Args:
        qgis_iface: The stubbed QgisInterface provided by pytest-qgis.
    """
    from modules.context import PluginContext  # noqa: PLC0415

    plugin_dir: Path = Path(__file__).parent.parent
    PluginContext.init(qgis_iface, plugin_dir)


# ---------------------------------------------------------------------------
# Convenience fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def plugin_dir() -> Path:
    """Return the absolute path to the plugin root directory.

    Returns:
        Path to the repository root (parent of ``tests/``).
    """
    return Path(__file__).parent.parent


@pytest.fixture
def tmp_gpkg(tmp_path: Path) -> Path:
    """Return a path for a temporary GeoPackage that does not exist yet.

    Args:
        tmp_path: pytest's built-in temporary directory fixture.

    Returns:
        Path pointing to ``<tmp>/test.gpkg`` (file not yet created).
    """
    return tmp_path / "test.gpkg"


@pytest.fixture
def memory_point_layer() -> QgsVectorLayer:
    """Create an in-memory point layer with no features.

    Returns:
        A valid, empty ``QgsVectorLayer`` using the memory provider.
    """
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "test_points", "memory")
    assert layer.isValid(), "Could not create in-memory point layer."
    return layer


@pytest.fixture
def memory_line_layer() -> QgsVectorLayer:
    """Create an in-memory line layer with no features.

    Returns:
        A valid, empty ``QgsVectorLayer`` using the memory provider.
    """
    layer = QgsVectorLayer("LineString?crs=EPSG:4326", "test_lines", "memory")
    assert layer.isValid(), "Could not create in-memory line layer."
    return layer


@pytest.fixture
def clean_project(qgis_new_project: QgsProject) -> QgsProject:
    """Return a clean QgsProject with no layers.

    Wraps the ``qgis_new_project`` fixture from pytest-qgis, which
    removes all layers and configuration before each test.

    Args:
        qgis_new_project: pytest-qgis fixture that resets the project.

    Returns:
        The current (clean) ``QgsProject`` instance.
    """
    return qgis_new_project
