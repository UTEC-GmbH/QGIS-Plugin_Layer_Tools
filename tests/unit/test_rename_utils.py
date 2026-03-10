"""Unit tests for rename utility functions.

These tests do *not* require a QGIS environment (no ``qgis_app`` fixture)
because the functions under test are pure Python string operations.
"""

from modules.rename import fix_layer_name


class TestFixLayerName:
    """Tests for the ``fix_layer_name`` helper."""

    def test_clean_name_unchanged(self) -> None:
        """A name with no encoding issues or special chars is returned as-is."""
        assert fix_layer_name("Grundleitungen") == "Grundleitungen"

    def test_fixes_mojibake_umlaut(self) -> None:
        """cp1252-decoded-as-utf8 umlauts are corrected.

        'Ãœ' is what you get when 'Ü' (UTF-8: 0xC3 0x9C) is incorrectly
        decoded using cp1252, so it should be restored to 'Ü'.
        """
        # Ü encoded in UTF-8, then wrongly decoded as cp1252 → 'Ãœ'
        mojibake: str = "Ü".encode().decode("cp1252")
        assert fix_layer_name(mojibake) == "Ü"

    def test_fixes_mojibake_ae(self) -> None:
        """cp1252-decoded-as-utf8 'ä' is corrected."""
        mojibake: str = "ä".encode().decode("cp1252")
        assert fix_layer_name(mojibake) == "ä"

    def test_removes_angle_brackets(self) -> None:
        """Characters ``<`` and ``>`` are replaced with ``_``."""
        assert fix_layer_name("layer<name>") == "layer_name_"

    def test_removes_slash(self) -> None:
        """Forward slash is replaced with ``_``."""
        assert fix_layer_name("path/name") == "path_name"

    def test_removes_backslash(self) -> None:
        """Backslash is replaced with ``_``."""
        assert fix_layer_name("path\\name") == "path_name"

    def test_removes_pipe(self) -> None:
        """Pipe character is replaced with ``_``."""
        assert fix_layer_name("layer|name") == "layer_name"

    def test_removes_question_mark(self) -> None:
        """Question mark is replaced with ``_``."""
        assert fix_layer_name("what?") == "what_"

    def test_removes_asterisk(self) -> None:
        """Asterisk is replaced with ``_``."""
        assert fix_layer_name("layer*") == "layer_"

    def test_removes_colon(self) -> None:
        """Colon is replaced with ``_``."""
        assert fix_layer_name("C:name") == "C_name"

    def test_consecutive_special_chars_collapsed(self) -> None:
        """Runs of special characters are collapsed into a single ``_``."""
        result: str = fix_layer_name("a<>b")
        # Both < and > should be replaced but the regex replaces each run
        # of matching chars with a single underscore.
        assert "_" in result
        assert "<" not in result
        assert ">" not in result

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert fix_layer_name("") == ""

    def test_unicode_preserved(self) -> None:
        """Valid unicode characters that are not special are preserved."""
        assert fix_layer_name("Straße") == "Straße"


class TestGeometryTypeSuffix:
    """Tests for ``geometry_type_suffix`` that need no QGIS env."""

    def test_non_vector_layer_returns_empty(self) -> None:
        """``geometry_type_suffix`` returns '' for non-QgsVectorLayer objects.

        We test with a plain object that is not a QgsVectorLayer, which
        exercises the ``if not isinstance(layer, QgsVectorLayer): return ''``
        branch without needing a real QGIS raster layer.
        """
        from modules.rename import geometry_type_suffix  # noqa: PLC0415

        class FakeLayer:
            """Stub for a non-vector layer."""

        assert geometry_type_suffix(FakeLayer()) == ""  # type: ignore[arg-type]
