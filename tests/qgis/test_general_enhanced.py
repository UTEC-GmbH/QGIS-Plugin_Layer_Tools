"""Enhanced integration tests for modules/general.py."""

from unittest.mock import MagicMock, patch

import pytest
from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer, QgsProject, QgsVectorLayer
from qgis.gui import QgisInterface, QgsLayerTreeView

from modules.general import get_selected_layers
from modules.logs_and_errors import CustomUserError


@pytest.mark.usefixtures("qgis_iface")
class TestGetSelectedLayers:
    """Enhanced tests for ``get_selected_layers``."""

    @pytest.fixture(autouse=True)
    def setup_iface(self, qgis_iface: QgisInterface) -> None:
        """Ensure layerTreeView and messageBar methods are mocked on iface."""
        if not hasattr(qgis_iface, "layerTreeView"):
            qgis_iface.layerTreeView = MagicMock(spec=QgsLayerTreeView)

        if mb := qgis_iface.messageBar():
            if not hasattr(mb, "clearWidgets"):
                mb.clearWidgets = MagicMock()
            if not hasattr(mb, "pushMessage"):
                mb.pushMessage = MagicMock()
            else:
                # If it exists but signature is incompatible with our call, mock it
                mb.pushMessage = MagicMock()

    def test_get_selected_layers_no_selection_raises_error(
        self, qgis_iface: QgisInterface
    ) -> None:
        """If no layers are selected, a CustomUserError is raised."""
        with (
            patch.object(qgis_iface.layerTreeView(), "selectedNodes", return_value=[]),
            pytest.raises(CustomUserError, match=r"No layers or groups selected."),
        ):
            get_selected_layers()

    def test_get_selected_layers_single_layer(self, qgis_iface: QgisInterface) -> None:
        """Test with a single selected layer node."""
        layer = QgsVectorLayer("Point?field=id:integer", "layer1", "memory")
        QgsProject.instance().addMapLayer(layer)

        node = QgsLayerTreeLayer(layer)

        with patch.object(
            qgis_iface.layerTreeView(), "selectedNodes", return_value=[node]
        ):
            selected = get_selected_layers()
            assert len(selected) == 1
            assert selected[0].id() == layer.id()

    def test_get_selected_layers_group_recursive(
        self, qgis_iface: QgisInterface
    ) -> None:
        """If a group is selected, all its layers should be returned."""
        layer1 = QgsVectorLayer("Point", "l1", "memory")
        layer2 = QgsVectorLayer("Point", "l2", "memory")
        QgsProject.instance().addMapLayers([layer1, layer2])

        group = QgsLayerTreeGroup("Group")
        group.addLayer(layer1)
        group.addLayer(layer2)

        with patch.object(
            qgis_iface.layerTreeView(), "selectedNodes", return_value=[group]
        ):
            selected = get_selected_layers()
            assert len(selected) == 2
            assert {layer_obj.id() for layer_obj in selected} == {
                layer1.id(),
                layer2.id(),
            }

    def test_get_selected_layers_sorted_visual_order(
        self, qgis_iface: QgisInterface
    ) -> None:
        """Selected layers should be sorted by visual order (top to bottom)."""
        layer_top = QgsVectorLayer("Point", "top", "memory")
        layer_bottom = QgsVectorLayer("Point", "bottom", "memory")

        # Add to project - usually bottom is added first or we use layerTree
        project = QgsProject.instance()
        project.addMapLayer(layer_bottom)  # Added first -> bottom
        project.addMapLayer(layer_top)  # Added second -> top (usually)

        # Ensure visual order in tree
        root = project.layerTreeRoot()
        root.clear()
        node_top = root.addLayer(layer_top)
        node_bottom = root.addLayer(layer_bottom)

        # Mock selection in reverse order
        with patch.object(
            qgis_iface.layerTreeView(),
            "selectedNodes",
            return_value=[node_bottom, node_top],
        ):
            selected = get_selected_layers()
            # Should be [layer_top, layer_bottom]
            assert selected[0].id() == layer_top.id()
            assert selected[1].id() == layer_bottom.id()
