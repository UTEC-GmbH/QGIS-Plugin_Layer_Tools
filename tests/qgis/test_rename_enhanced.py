"""Enhanced integration tests for modules/rename.py."""

from qgis.core import QgsVectorLayer

from modules.rename import (
    Rename,
    fix_layer_name,
    geometry_type_suffix,
    handle_name_collisions,
)


class TestRenameEnhanced:
    """Enhanced tests for renaming functions."""

    def test_fix_layer_name_mojibake(self) -> None:
        """Test fixing mojibake in layer names."""
        # 'Ãœ' encoded in cp1252 but actually utf-8 is 'Ü'
        garbled = "Ãœbersee"
        assert fix_layer_name(garbled) == "Übersee"

    def test_fix_layer_name_sanitization(self) -> None:
        """Test sanitization of problematic characters."""
        problematic = 'Layer: <"Name"> / \\ | ? * ,'
        # re.sub(r'[<>:"/\\|?*,]+', "_", fixed_name)
        # Expected: "Layer_ _Name__ _ _ _ _ _ _" - multiple chars replaced by single _?
        # No, r'[...]+' replaces sequences with a single _.
        # Wait, let's check:
        # 'Layer: ' -> 'Layer_ '
        # '<"Name">' -> '_Name_'
        # ' / \\ | ? * ,' -> ' _ '
        # Actually it depends on the spaces.
        result = fix_layer_name(problematic)
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "/" not in result

    def test_handle_name_collisions_suffixes(self) -> None:
        """Test that collisions get geometry suffixes for non-empty layers."""
        layer1 = QgsVectorLayer("Point", "old1", "memory")
        # Add a feature to make it non-empty
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

        f1 = QgsFeature()
        f1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
        if provider := layer1.dataProvider():
            provider.addFeatures([f1])
        layer1.setName("old1")

        layer2 = QgsVectorLayer("LineString", "old2", "memory")
        # Add a feature to make it non-empty
        f2 = QgsFeature()
        # Geometry doesn't strictly matter for is_empty_layer, it just needs features
        if provider := layer2.dataProvider():
            provider.addFeatures([f2])
        layer2.setName("old2")

        renames = [Rename(layer1, "old1", "NewName"), Rename(layer2, "old2", "NewName")]

        plan = handle_name_collisions(renames)
        assert len(plan) == 2

        # Determine which is which
        l1_plan = next(r for r in plan if r.layer == layer1)
        l2_plan = next(r for r in plan if r.layer == layer2)

        assert l1_plan.new_name == "NewName - pt"
        assert l2_plan.new_name == "NewName - l"

    def test_handle_name_collisions_no_rename_if_same(self) -> None:
        """If the new name is same as current, it should be excluded (unless collision)."""
        layer = QgsVectorLayer("Point", "SameName", "memory")
        renames = [Rename(layer, "SameName", "SameName")]

        plan = handle_name_collisions(renames)
        # It should be empty because we don't need to rename to the same name
        assert len(plan) == 0

    def test_geometry_type_suffix_pl_exception(self) -> None:
        """Test the special case for 'polylines' or ' - pl' suffix."""
        layer = QgsVectorLayer("LineString", "polylines", "memory")
        assert geometry_type_suffix(layer) == " - pl"

        layer2 = QgsVectorLayer("LineString", "anything - pl", "memory")
        assert geometry_type_suffix(layer2) == " - pl"
