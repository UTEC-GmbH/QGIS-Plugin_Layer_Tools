"""QGIS integration tests for modules/general.py.

These tests require a running ``QgsApplication`` (provided by pytest-qgis).
They test layer utility functions: ``is_empty_layer`` and
``clear_attribute_table``.
"""

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from modules.general import clear_attribute_table, is_empty_layer

# ---------------------------------------------------------------------------
# is_empty_layer
# ---------------------------------------------------------------------------


class TestIsEmptyLayer:
    """Tests for ``is_empty_layer``."""

    def test_empty_vector_layer_returns_true(self) -> None:
        """A valid vector layer with no features is considered empty."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "empty", "memory")
        assert layer.isValid()
        assert is_empty_layer(layer) is True

    def test_layer_with_feature_returns_false(self) -> None:
        """A vector layer with at least one feature is NOT empty."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "not_empty", "memory")
        assert layer.isValid()

        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0.0, 0.0)))
        if provider := layer.dataProvider():
            provider.addFeatures([feature])

        assert is_empty_layer(layer) is False

    def test_invalid_layer_returns_false(self) -> None:
        """An invalid layer is treated as non-empty (returns False).

        The function's contract: only valid vector layers can be "empty".
        """
        layer = QgsVectorLayer("", "bad", "memory")
        assert not layer.isValid()
        assert is_empty_layer(layer) is False

    def test_non_vector_layer_returns_false(self) -> None:
        """``is_empty_layer`` always returns False for non-vector layers.

        We test with a ``QgsRasterLayer`` constructed with an invalid path,
        which will be invalid — but the function short-circuits on type
        before checking validity.
        """
        # An invalid raster layer still satisfies isinstance(…, QgsRasterLayer).
        layer = QgsRasterLayer("", "fake_raster", "gdal")
        assert is_empty_layer(layer) is False


# ---------------------------------------------------------------------------
# clear_attribute_table
# ---------------------------------------------------------------------------


class TestClearAttributeTable:
    """Tests for ``clear_attribute_table``."""

    def test_removes_all_fields(self) -> None:
        """All fields are deleted from the layer's attribute table."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "with_fields", "memory")
        assert layer.isValid()

        if provider := layer.dataProvider():
            provider.addAttributes(
                [
                    QgsField("name", QVariant.String),
                    QgsField("value", QVariant.Int),
                ]
            )
        layer.updateFields()
        assert layer.fields().count() == 2  # noqa: PLR2004

        clear_attribute_table(layer)
        assert layer.fields().count() == 0

    def test_no_fields_is_a_noop(self) -> None:
        """Calling on a layer with no fields does not raise."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "no_fields", "memory")
        assert layer.isValid()

        # Should not raise.
        clear_attribute_table(layer)
        assert layer.fields().count() == 0

    def test_non_vector_layer_is_a_noop(self) -> None:
        """Calling with a non-vector layer object does not raise."""
        # An invalid raster layer satisfies isinstance check for non-vector case.
        raster = QgsRasterLayer("", "fake_raster", "gdal")
        # Should not raise.
        clear_attribute_table(raster)
