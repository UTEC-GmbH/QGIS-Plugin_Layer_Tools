"""Unit tests for the layer_location module."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.constants import LayerLocation
from modules.layer_location import (
    _create_multi_indicator_tooltip,
    get_layer_location,
    get_layer_source_path,
    is_cloud_layer,
)


@pytest.fixture
def mock_layer() -> MagicMock:
    """Fixture for a mocked QgsMapLayer."""
    layer = MagicMock()
    layer.source.return_value = "C:/data/test.gpkg|layername=test_table"
    layer.providerType.return_value = "ogr"
    layer.id.return_value = "test_layer_id"
    layer.name.return_value = "Test Layer"
    return layer


@pytest.fixture
def mock_registry() -> MagicMock:
    """Fixture for a mocked QgsProviderRegistry."""
    with patch("qgis.core.QgsProviderRegistry.instance") as mock_instance:
        registry = MagicMock()
        mock_instance.return_value = registry
        yield registry


class TestGetLayerSourcePath:
    """Tests for get_layer_source_path function."""

    def test_local_path(self, mock_layer: MagicMock, mock_registry: MagicMock) -> None:
        """Test with a standard local GeoPackage path."""
        mock_registry.decodeUri.return_value = {"path": "C:/data/test.gpkg"}
        path = get_layer_source_path(mock_layer)
        assert path == os.path.normcase("C:/data/test.gpkg")

    def test_memory_layer(self, mock_layer: MagicMock) -> None:
        """Test with a memory layer."""
        mock_layer.source.return_value = "memory:"
        path = get_layer_source_path(mock_layer)
        assert path is None

    def test_no_path_in_uri(
        self, mock_layer: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Test fallback when decoded URI has no path."""
        mock_registry.decodeUri.return_value = {}
        mock_layer.source.return_value = "C:/data/test.gpkg|layername=table"
        path = get_layer_source_path(mock_layer)
        assert path == os.path.normcase("C:/data/test.gpkg")


class TestIsCloudLayer:
    """Tests for is_cloud_layer function."""

    def test_cloud_url_in_uri(
        self, mock_layer: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Test with a URL in the decoded URI."""
        mock_registry.decodeUri.return_value = {"url": "https://example.com/wms"}
        assert is_cloud_layer(mock_layer) is True

    def test_http_prefix(self, mock_layer: MagicMock, mock_registry: MagicMock) -> None:
        """Test with an http prefix in the source."""
        mock_registry.decodeUri.return_value = {}
        mock_layer.source.return_value = "http://example.com/data"
        assert is_cloud_layer(mock_layer) is True

    def test_local_file(self, mock_layer: MagicMock, mock_registry: MagicMock) -> None:
        """Test with a local file (not a cloud layer)."""
        mock_registry.decodeUri.return_value = {"path": "C:/data/test.gpkg"}
        mock_layer.source.return_value = "C:/data/test.gpkg"
        assert is_cloud_layer(mock_layer) is False


class TestGetLayerLocation:
    """Tests for get_layer_location function."""

    @patch("modules.layer_location.PluginContext.project_gpkg")
    @patch("qgis.core.QgsProject.instance")
    def test_gpkg_project(
        self,
        mock_project_instance: MagicMock,
        mock_project_gpkg: MagicMock,
        mock_layer: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Test when layer is in the project's GeoPackage."""
        project = MagicMock()
        project.fileName.return_value = "C:/projects/test.qgz"
        mock_project_instance.return_value = project

        mock_project_gpkg.return_value = Path("C:/projects/test.gpkg")

        mock_registry.decodeUri.return_value = {"path": "C:/projects/test.gpkg"}
        mock_layer.source.return_value = "C:/projects/test.gpkg|layername=table"

        assert get_layer_location(mock_layer) == LayerLocation.GPKG_PROJECT

    @patch("modules.layer_location.PluginContext.project_gpkg")
    @patch("qgis.core.QgsProject.instance")
    def test_external_location(
        self,
        mock_project_instance: MagicMock,
        mock_project_gpkg: MagicMock,
        mock_layer: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Test when layer is outside the project folder."""
        project = MagicMock()
        project.fileName.return_value = "C:/projects/test.qgz"
        mock_project_instance.return_value = project

        mock_project_gpkg.return_value = Path("C:/projects/test.gpkg")

        mock_registry.decodeUri.return_value = {"path": "D:/other_data/data.gpkg"}
        mock_layer.source.return_value = "D:/other_data/data.gpkg"

        assert get_layer_location(mock_layer) == LayerLocation.EXTERNAL

    @patch("qgis.core.QgsProject.instance")
    def test_no_project_saved(
        self, mock_project_instance: MagicMock, mock_layer: MagicMock
    ) -> None:
        """Test when project is not saved."""
        project = MagicMock()
        project.fileName.return_value = ""
        mock_project_instance.return_value = project

        assert get_layer_location(mock_layer) is None


class TestCreateMultiIndicatorTooltip:
    """Tests for _create_multi_indicator_tooltip function."""

    @patch("qgis.core.QgsProviderRegistry.instance")
    @patch("qgis.PyQt.QtCore.QCoreApplication.translate")
    def test_tooltip_generation(
        self,
        mock_translate: MagicMock,
        mock_registry_instance: MagicMock,
        mock_layer: MagicMock,
    ) -> None:
        """Test HTML tooltip generation."""
        mock_translate.side_effect = lambda _x, y: y

        registry = MagicMock()
        mock_registry_instance.return_value = registry
        registry.decodeUri.return_value = {
            "path": "C:/data/test.gpkg",
            "layerName": "test_table",
        }

        project = MagicMock()
        project.fileName.return_value = "C:/data/project.qgz"

        shared_names = ["Layer A", "Layer B"]

        tooltip = _create_multi_indicator_tooltip(project, mock_layer, shared_names)

        assert "Shared Data Source" in tooltip
        assert "Layer A" in tooltip
        assert "Layer B" in tooltip
        assert "test_table" in tooltip
