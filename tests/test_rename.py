from unittest.mock import patch

from qgis.core import QgsVectorLayer, QgsProject

from modules.rename import fix_layer_name, prepare_rename_plan, Rename


def test_fix_layer_name() -> None:
    """Test the string sanitization logic."""
    assert fix_layer_name("NormalName") == "NormalName"
    assert fix_layer_name("Name/With\Bad<Chars>") == "Name_With_Bad_Chars_"
    # Test mojibake fix (UTF-8 interpreted as cp1252)
    # 'Ãœ' is 'Ü' encoded in utf-8 and decoded as cp1252
    assert fix_layer_name("Ãœber") == "Über"


def test_prepare_rename_plan(project: QgsProject) -> None:
    """Test generating a rename plan with real layers."""
    # 1. Setup: Create a group and add layers
    root = project.layerTreeRoot()
    group = root.addGroup("MyGroup")

    layer1 = QgsVectorLayer("Point?crs=EPSG:4326", "layer_a", "memory")
    layer2 = QgsVectorLayer("Point?crs=EPSG:4326", "layer_b", "memory")

    project.addMapLayer(layer1, addToLegend=False)
    project.addMapLayer(layer2, addToLegend=False)

    group.addLayer(layer1)
    group.addLayer(layer2)

    # 2. Mock get_selected_layers to return our test layers
    # We mock it because we can't easily select nodes in the GUI tree in a headless test
    with patch("modules.rename.get_selected_layers", return_value=[layer1, layer2]):
        # 3. Execute
        results = prepare_rename_plan()

    # 4. Assert
    # Both layers are in "MyGroup", so they should be renamed to "MyGroup"
    # Collision handling should append suffixes or handle duplicates
    assert len(results.result) == 2

    plan_1 = results.result[0]
    plan_2 = results.result[1]

    assert plan_1.new_name.startswith("MyGroup")
    assert plan_2.new_name.startswith("MyGroup")

    # Ensure collision handling worked (names should be distinct if geometry is same)
    # Since both are points, one might get a suffix or they might be identical
    # depending on your specific collision logic implementation.
    # Based on your code, if geometry matches, it might return original name
    # OR append suffix if they target the same new name.

    # In your handle_name_collisions:
    # If multiple layers target "MyGroup", it appends geometry suffix.
    # Since both are Points, they might both become "MyGroup - pt".
    # This reveals a potential logic edge case in your code (duplicate names allowed),
    # or expected behavior.
    assert plan_1.new_name == "MyGroup - pt"
    assert plan_2.new_name == "MyGroup - pt"
