"""QGIS integration tests for modules/rename.py.

These tests require a running ``QgsApplication`` (provided by pytest-qgis).
They test the rename plan building and execution logic against real
``QgsVectorLayer`` objects.
"""

from qgis.core import QgsFeature, QgsVectorLayer

from modules.rename import Rename, execute_rename_plan, handle_name_collisions

# ---------------------------------------------------------------------------
# handle_name_collisions
# ---------------------------------------------------------------------------


class TestHandleNameCollisions:
    """Tests for ``handle_name_collisions``."""

    def test_no_collision_layer_is_renamed(self) -> None:
        """Single rename with unique target name is kept as-is."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "original", "memory")
        assert layer.isValid()

        renames: list[Rename] = [Rename(layer, "original", "new_name")]
        plan: list[Rename] = handle_name_collisions(renames)

        assert len(plan) == 1
        assert plan[0].new_name == "new_name"

    def test_already_matching_name_excluded(self) -> None:
        """A layer whose current name equals the proposed name is excluded."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "same_name", "memory")
        assert layer.isValid()

        renames: list[Rename] = [Rename(layer, "same_name", "same_name")]
        plan: list[Rename] = handle_name_collisions(renames)

        assert not plan

    def test_collision_adds_geometry_suffix(self) -> None:
        """Two layers with the same target name get a geometry suffix.

        A point and a line layer both wanting the name 'road' should each
        receive a unique suffixed name.
        """
        point_layer = QgsVectorLayer("Point?crs=EPSG:4326", "pt_layer", "memory")
        line_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "ln_layer", "memory")
        assert point_layer.isValid()
        assert line_layer.isValid()

        # Add a feature to each so they aren't considered empty
        # (empty layers don't get geometry suffixes in handle_name_collisions)
        for lyr in (point_layer, line_layer):
            if lyr_prov := lyr.dataProvider():
                feat = QgsFeature()
                lyr_prov.addFeatures([feat])

        renames: list[Rename] = [
            Rename(point_layer, "pt_layer", "road"),
            Rename(line_layer, "ln_layer", "road"),
        ]
        plan: list[Rename] = handle_name_collisions(renames)

        new_names: set[str] = {r.new_name for r in plan if r.new_name}
        # Both suffixed names must be unique and different from each other.
        assert len(new_names) == 2  # noqa: PLR2004 (magic value intentional)
        # The base name 'road' should be embedded in each result.
        for name in new_names:
            assert "road" in name

    def test_error_renames_preserved(self) -> None:
        """Rename entries without a ``new_name`` (errors/skips) are kept.

        An entry with ``new_name=None`` signals a skip/error and must pass
        through the function unchanged.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "x", "memory")
        assert layer.isValid()

        error_entry = Rename(layer, "x", None, error="some error")
        plan: list[Rename] = handle_name_collisions([error_entry])

        assert len(plan) == 1
        assert plan[0].error == "some error"


# ---------------------------------------------------------------------------
# execute_rename_plan
# ---------------------------------------------------------------------------


class TestExecuteRenamePlan:
    """Tests for ``execute_rename_plan``."""

    def test_renames_layer(self) -> None:
        """``execute_rename_plan`` renames a layer to its target name.

        Args: (implicitly from pytest fixtures) — none required.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "before", "memory")
        assert layer.isValid()

        plan: list[Rename] = [Rename(layer, "before", "after")]
        execute_rename_plan(plan)

        assert layer.name() == "after"

    def test_records_successful_rename(self) -> None:
        """Successful renames appear in ``result`` (used to build undo stack)."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "alpha", "memory")
        assert layer.isValid()

        plan: list[Rename] = [Rename(layer, "alpha", "beta")]
        result = execute_rename_plan(plan)

        assert result.successes  # at least one success recorded
        assert result.result  # undo tuple present
        layer_id, old, new = result.result[0]
        assert layer_id == layer.id()
        assert old == "alpha"
        assert new == "beta"

    def test_skips_entry_with_skip_reason(self) -> None:
        """Entries with a ``skip`` reason are not renamed."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "unchanged", "memory")
        assert layer.isValid()

        plan: list[Rename] = [
            Rename(layer, "unchanged", "should_not_be_used", skip="not in group")
        ]
        execute_rename_plan(plan)

        # Layer name should remain unchanged.
        assert layer.name() == "unchanged"

    def test_error_entry_does_not_rename(self) -> None:
        """Entries with an ``error`` value are skipped."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "stays", "memory")
        assert layer.isValid()

        plan: list[Rename] = [
            Rename(layer, "stays", "new", error="something went wrong")
        ]
        result = execute_rename_plan(plan)

        assert layer.name() == "stays"
        assert result.errors

    def test_multiple_renames_all_succeed(self) -> None:
        """Multiple layers in the plan are all renamed correctly."""
        layer_a = QgsVectorLayer("Point?crs=EPSG:4326", "a", "memory")
        layer_b = QgsVectorLayer("LineString?crs=EPSG:4326", "b", "memory")
        assert layer_a.isValid()
        assert layer_b.isValid()

        plan: list[Rename] = [
            Rename(layer_a, "a", "A_renamed"),
            Rename(layer_b, "b", "B_renamed"),
        ]
        result = execute_rename_plan(plan)

        assert layer_a.name() == "A_renamed"
        assert layer_b.name() == "B_renamed"
        assert len(result.successes) == 2  # noqa: PLR2004
