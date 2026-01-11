import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add the plugin root directory to sys.path so we can import modules
PLUGIN_DIR = Path(__file__).parent.parent
sys.path.append(str(PLUGIN_DIR))

# Import QGIS modules after setting up path if necessary,
# but usually run this from OSGeo4W shell where qgis is available.
from qgis.core import QgsApplication, QgsProject  # noqa: E402
from qgis.gui import QgisInterface  # noqa: E402

from modules.context import PluginContext  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def qgis_app() -> QgsApplication:
    """Initialize QGIS Application for the test session.

    This is required to use any QGIS API classes (QgsVectorLayer, etc.)
    without crashing.
    """
    # Supply path to qgis installation if needed, or use empty string if in OSGeo4W
    qgs = QgsApplication([], False)
    qgs.initQgis()
    yield qgs
    qgs.exitQgis()


@pytest.fixture
def project() -> QgsProject:
    """Provide a fresh QgsProject for each test."""
    project = QgsProject.instance()
    project.clear()
    return project


@pytest.fixture
def mock_iface() -> MagicMock:
    """Create a mock QgisInterface.

    This allows us to test code that calls iface methods without a real GUI.
    """
    iface = MagicMock(spec=QgisInterface)
    # Mock messageBar to avoid errors in logs_and_errors.py
    iface.messageBar.return_value = MagicMock()
    return iface


@pytest.fixture(autouse=True)
def init_context(mock_iface: MagicMock) -> None:
    """Initialize PluginContext before each test.

    This ensures PluginContext.iface() and PluginContext.project() work
    during tests.
    """
    PluginContext.init(mock_iface, PLUGIN_DIR)
