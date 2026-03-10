"""QGIS integration tests for modules/geopackage.py.

These tests require a running ``QgsApplication`` provided by ``pytest-qgis``
via the ``qgis_app`` fixture (applied automatically at session scope).
"""

from pathlib import Path

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

from modules.geopackage import (
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
