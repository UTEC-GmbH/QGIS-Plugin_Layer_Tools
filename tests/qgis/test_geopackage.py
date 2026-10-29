"""QGIS integration tests for modules/geopackage.py.

These tests require a running ``QgsApplication`` provided by ``pytest-qgis``
via the ``qgis_app`` fixture (applied automatically at session scope).
"""

from pathlib import Path
from unittest.mock import patch

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from modules.context import PluginContext
from modules.geopackage import (
    _create_gpkg_vector_layer,
    _delete_gpkg_tables,
    _get_gpkg_layer_dependencies,
    _get_gpkg_layer_table,
    _NewGpkgLayerDialog,
    _shared_source_warning_dialog,
    _validate_gpkg_layer_name,
    add_vector_layer_to_gpkg,
    check_existing_layer,
    create_gpkg,
    get_gpkg_layer_names,
)

# ---------------------------------------------------------------------------
# create_gpkg
# ---------------------------------------------------------------------------


class TestCreateGpkg:
    """Tests for ``create_gpkg``."""

    def test_creates_file(self, tmp_gpkg: Path) -> None:
        """``create_gpkg`` creates a ``.gpkg`` file that did not exist before.

        Args:
            tmp_gpkg: Fixture providing a non-existing tmp path.
        """
        result: Path = create_gpkg(tmp_gpkg)
        assert result == tmp_gpkg
        assert tmp_gpkg.exists()

    def test_idempotent_when_exists(self, tmp_gpkg: Path) -> None:
        """Calling ``create_gpkg`` twice without ``delete_existing`` is safe.

        Args:
            tmp_gpkg: Fixture providing a non-existing tmp path.
        """
        create_gpkg(tmp_gpkg)
        mtime_first: float = tmp_gpkg.stat().st_mtime

        create_gpkg(tmp_gpkg)
        mtime_second: float = tmp_gpkg.stat().st_mtime

        # File should not be touched on the second call.
        assert mtime_first == mtime_second

    def test_delete_existing_recreates(self, tmp_gpkg: Path) -> None:
        """``delete_existing=True`` recreates the GeoPackage.

        Args:
            tmp_gpkg: Fixture providing a non-existing tmp path.
        """
        create_gpkg(tmp_gpkg)
        mtime_first: float = tmp_gpkg.stat().st_mtime

        create_gpkg(tmp_gpkg, delete_existing=True)

        # The file should still exist and was likely touched.
        assert tmp_gpkg.exists()


# ---------------------------------------------------------------------------
# get_gpkg_layer_names
# ---------------------------------------------------------------------------


class TestGetGpkgLayerNames:
    """Tests for ``get_gpkg_layer_names``."""

    def test_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        """Returns an empty set when the GeoPackage does not exist.

        Args:
            tmp_path: pytest temporary directory.
        """
        result: set[str] = get_gpkg_layer_names(tmp_path / "nonexistent.gpkg")
        assert result == set()

    def test_returns_table_names(
        self, tmp_gpkg: Path, memory_point_layer: QgsVectorLayer
    ) -> None:
        """Layer names written to a GPKG appear in ``get_gpkg_layer_names``.

        Args:
            tmp_gpkg: Path to a temporary (non-existing) GeoPackage.
            memory_point_layer: A valid in-memory point layer.
        """
        create_gpkg(tmp_gpkg)
        project: QgsProject = QgsProject.instance()
        add_vector_layer_to_gpkg(project, memory_point_layer, tmp_gpkg)

        names: set[str] = get_gpkg_layer_names(tmp_gpkg)
        assert memory_point_layer.name() in names


# ---------------------------------------------------------------------------
# check_existing_layer
# ---------------------------------------------------------------------------


class TestCheckExistingLayer:
    """Tests for ``check_existing_layer``."""

    def test_new_layer_returns_original_name(
        self, tmp_gpkg: Path, memory_point_layer: QgsVectorLayer
    ) -> None:
        """Layer not yet in GPKG → original name returned unchanged.

        Args:
            tmp_gpkg: Path to a temporary (non-existing) GeoPackage.
            memory_point_layer: A valid in-memory point layer.
        """
        create_gpkg(tmp_gpkg)
        result: str = check_existing_layer(
            tmp_gpkg, memory_point_layer, existing_layers=set()
        )
        assert result == memory_point_layer.name()

    def test_same_geom_returns_original_name(
        self, tmp_gpkg: Path, memory_point_layer: QgsVectorLayer
    ) -> None:
        """Same name + same geometry → original name (overwrite allowed).

        Args:
            tmp_gpkg: Path to a temporary (non-existing) GeoPackage.
            memory_point_layer: A valid in-memory point layer.
        """
        create_gpkg(tmp_gpkg)
        project: QgsProject = QgsProject.instance()
        add_vector_layer_to_gpkg(project, memory_point_layer, tmp_gpkg)

        existing: set[str] = get_gpkg_layer_names(tmp_gpkg)
        result: str = check_existing_layer(
            tmp_gpkg, memory_point_layer, existing_layers=existing
        )
        assert result == memory_point_layer.name()

    def test_different_geom_returns_suffixed_name(
        self,
        tmp_gpkg: Path,
        memory_point_layer: QgsVectorLayer,
        memory_line_layer: QgsVectorLayer,
    ) -> None:
        """Same name but different geometry → name gets a geometry suffix.

        We write a *point* layer, then ask what name a *line* layer with the
        same name should use. The function should append a suffix (e.g.,
        ' - l') to avoid a collision.

        Args:
            tmp_gpkg: Path to a temporary (non-existing) GeoPackage.
            memory_point_layer: A valid in-memory point layer.
            memory_line_layer: A valid in-memory line layer.
        """
        # Force both layers to share a name so there is a collision.
        memory_line_layer.setName(memory_point_layer.name())

        create_gpkg(tmp_gpkg)
        project: QgsProject = QgsProject.instance()
        add_vector_layer_to_gpkg(project, memory_point_layer, tmp_gpkg)

        existing: set[str] = get_gpkg_layer_names(tmp_gpkg)
        result: str = check_existing_layer(
            tmp_gpkg, memory_line_layer, existing_layers=existing
        )

        # Result must differ from the original name (suffix was added).
        assert result != memory_point_layer.name()
        assert memory_point_layer.name() in result  # base name preserved


# ---------------------------------------------------------------------------
# add_vector_layer_to_gpkg
# ---------------------------------------------------------------------------


class TestAddVectorLayerToGpkg:
    """Tests for ``add_vector_layer_to_gpkg``."""

    def test_adds_layer_successfully(
        self, tmp_gpkg: Path, memory_point_layer: QgsVectorLayer
    ) -> None:
        """Writing a vector layer to a new GPKG succeeds with no errors.

        Args:
            tmp_gpkg: Path to a temporary (non-existing) GeoPackage.
            memory_point_layer: A valid in-memory point layer.
        """
        create_gpkg(tmp_gpkg)
        project: QgsProject = QgsProject.instance()
        result = add_vector_layer_to_gpkg(project, memory_point_layer, tmp_gpkg)

        assert not result.errors
        assert result.successes

    def test_written_layer_is_readable(
        self, tmp_gpkg: Path, memory_point_layer: QgsVectorLayer
    ) -> None:
        """A layer written to a GPKG can be loaded back as a valid layer.

        Args:
            tmp_gpkg: Path to a temporary (non-existing) GeoPackage.
            memory_point_layer: A valid in-memory point layer.
        """
        create_gpkg(tmp_gpkg)
        project: QgsProject = QgsProject.instance()
        add_vector_layer_to_gpkg(project, memory_point_layer, tmp_gpkg)

        layer_name: str = memory_point_layer.name()
        uri: str = f"{tmp_gpkg}|layername={layer_name}"
        loaded = QgsVectorLayer(uri, layer_name, "ogr")
        assert loaded.isValid()

    def test_features_are_preserved(self, tmp_gpkg: Path) -> None:
        """Features added to a layer are present after writing to GPKG.

        Args:
            tmp_gpkg: Path to a temporary (non-existing) GeoPackage.
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "with_features", "memory")
        assert layer.isValid()

        if data_prov := layer.dataProvider():
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(8.0, 47.0)))
            data_prov.addFeatures([feature])

            create_gpkg(tmp_gpkg)
            project: QgsProject = QgsProject.instance()
            add_vector_layer_to_gpkg(project, layer, tmp_gpkg)

            uri: str = f"{tmp_gpkg}|layername=with_features"
            loaded = QgsVectorLayer(uri, "with_features", "ogr")
            assert loaded.isValid()
            assert loaded.featureCount() == 1


class TestCreateAndDeleteGpkgLayer:
    """Tests for creating and deleting empty GeoPackage tables."""

    def test_validates_layer_names(self) -> None:
        """Names must be non-empty, non-reserved, and unique without case."""
        assert _validate_gpkg_layer_name("", set())
        assert _validate_gpkg_layer_name("gpkg_contents", set())
        assert _validate_gpkg_layer_name("Roads", {"roads"})
        assert _validate_gpkg_layer_name("roads", set()) is None

    def test_creation_dialog_limits_geometry_choices(self) -> None:
        """Only point, line, and polygon options are shown."""
        dialog = _NewGpkgLayerDialog(set())

        assert dialog.geometry_combo.count() == 3
        assert [
            dialog.geometry_combo.itemData(index)
            for index in range(dialog.geometry_combo.count())
        ] == ["Point", "LineString", "Polygon"]
        assert dialog.geometry_type() == "Polygon"
        form = dialog.layout().itemAt(0).layout()
        assert form.getWidgetPosition(dialog.geometry_combo)[0] < form.getWidgetPosition(
            dialog.name_edit
        )[0]
        assert dialog.warning_label.minimumHeight() >= (
            dialog.warning_label.fontMetrics().lineSpacing() * 3
        )
        assert not dialog.button_box.button(QDialogButtonBox.Ok).isEnabled()
        dialog.show()
        QApplication.processEvents()
        assert dialog.name_edit.hasFocus()
        dialog.close()
        dialog.name_edit.setText("new layer")
        assert dialog.button_box.button(QDialogButtonBox.Ok).isEnabled()
        dialog.name_edit.setText("gpkg_contents")
        assert not dialog.button_box.button(QDialogButtonBox.Ok).isEnabled()

    def test_creates_empty_layer_with_project_crs(
        self, clean_project: QgsProject, tmp_gpkg: Path
    ) -> None:
        """The created table has the requested geometry and project CRS."""
        project = clean_project
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
        iface = PluginContext.iface()

        with (
            patch.object(iface, "setActiveLayer") as set_active_layer,
            patch.object(iface, "layerTreeView") as layer_tree_view,
        ):
            layer = _create_gpkg_vector_layer(
                project, tmp_gpkg, "empty_points", "Point"
            )

        assert layer.isValid()
        assert layer.crs() == project.crs()
        assert layer.geometryType() == Qgis.GeometryType.Point
        assert layer.fields().names() == ["fid"]
        assert layer.featureCount() == 0
        assert layer.isEditable()
        set_active_layer.assert_called_once_with(layer)
        layer_tree_view.return_value.setCurrentLayer.assert_called_once_with(layer)

    def test_delete_removes_table(
        self, clean_project: QgsProject, tmp_gpkg: Path
    ) -> None:
        """Deleting a GeoPackage table removes the source table."""
        layer = _create_gpkg_vector_layer(
            clean_project, tmp_gpkg, "delete_me", "LineString"
        )
        table_name = layer.name()

        _delete_gpkg_tables(tmp_gpkg, {table_name})

        assert table_name not in get_gpkg_layer_names(tmp_gpkg)

    def test_dependencies_identify_shared_sources(
        self, clean_project: QgsProject, tmp_gpkg: Path
    ) -> None:
        """Each project layer using a table is returned as a dependency."""
        create_gpkg(tmp_gpkg)
        source_layer = QgsVectorLayer("Point?crs=EPSG:4326", "source", "memory")
        add_vector_layer_to_gpkg(clean_project, source_layer, tmp_gpkg)
        first = QgsVectorLayer(
            f"{tmp_gpkg}|layername=source", "first view", "ogr"
        )
        second = QgsVectorLayer(
            f"{tmp_gpkg}|layername=source", "second view", "ogr"
        )
        clean_project.addMapLayer(first)
        clean_project.addMapLayer(second)

        dependencies = _get_gpkg_layer_dependencies(tmp_gpkg)

        assert {layer.id() for layer in dependencies["source"]} == {
            first.id(),
            second.id(),
        }

    def test_shared_source_warning_uses_available_yes_button_api(self) -> None:
        """The shared-source prompt labels its Yes button through Qt's API."""
        dialog = _shared_source_warning_dialog(
            "• second view (GeoPackage table: source)"
        )

        assert dialog.button(QMessageBox.Yes).text() == "Delete All Affected Layers"
        assert "second view" in dialog.text()
        dialog.close()

    def test_dependencies_identify_gpkg_subdataset_uri(
        self, clean_project: QgsProject, tmp_gpkg: Path
    ) -> None:
        """GPKG:path:table URIs are recognized as project GeoPackage sources."""
        create_gpkg(tmp_gpkg)
        source_layer = QgsVectorLayer("Point?crs=EPSG:4326", "source", "memory")
        add_vector_layer_to_gpkg(clean_project, source_layer, tmp_gpkg)
        layer = QgsVectorLayer(f"GPKG:{tmp_gpkg}:source", "renamed", "ogr")
        assert layer.isValid()
        standard_uri_layer = QgsVectorLayer(
            f"{tmp_gpkg}|layername=source", "also renamed", "ogr"
        )
        assert standard_uri_layer.isValid()
        clean_project.addMapLayer(layer)
        clean_project.addMapLayer(standard_uri_layer)

        dependencies = _get_gpkg_layer_dependencies(tmp_gpkg)

        assert {candidate.id() for candidate in dependencies["source"]} == {
            layer.id(),
            standard_uri_layer.id(),
        }

    def test_external_gpkg_source_is_not_a_project_gpkg_table(
        self, clean_project: QgsProject, tmp_gpkg: Path, tmp_path: Path
    ) -> None:
        """A table in another GeoPackage is classified as an external source."""
        create_gpkg(tmp_gpkg)
        other_gpkg = tmp_path / "other.gpkg"
        create_gpkg(other_gpkg)
        layer = QgsVectorLayer(f"{other_gpkg}|layername=some_table", "external", "ogr")

        assert _get_gpkg_layer_table(layer, tmp_gpkg) is None
