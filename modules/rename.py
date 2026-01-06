"""Module: functions_rename.py

This module contains the function for renaming and moving layers
in a QGIS project based on their group names.
"""

import contextlib
import json
import re
from collections import defaultdict
from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMapLayer,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication

from .constants import GEOMETRY_SUFFIX_MAP
from .context import PluginContext
from .general import get_selected_layers, raise_runtime_error
from .logs_and_errors import log_debug, log_summary_message

if TYPE_CHECKING:
    from qgis.core import QgsLayerTree, QgsLayerTreeNode


def fix_layer_name(name: str) -> str:
    """Fix encoding mojibake and sanitize a string to be a valid layer name.

    This function first attempts to fix a common mojibake encoding issue,
    where a UTF-8 string was incorrectly decoded as cp1252
    (for example: 'Ãœ' becomes 'Ü').
    It then sanitizes the string to remove or replace characters
    that might be problematic in layer names,
    especially for file-based formats or databases.

    Args:
        name: The potentially garbled and raw layer name.

    Returns:
        str: A fixed and sanitized version of the name.
    """
    fixed_name: str = name
    with contextlib.suppress(UnicodeEncodeError):
        fixed_name = name.encode("cp1252").decode("utf-8")

    # Remove or replace problematic characters
    sanitized_name: str = re.sub(r'[<>:"/\\|?*,]+', "_", fixed_name)

    return sanitized_name


def prepare_rename_plan() -> tuple[list[tuple[QgsMapLayer, str, str]], list[str]]:
    """Prepare a plan to rename selected layers based on their parent group.

    Empty vector layers are planned to be renamed to 'empty layer'. For other
    layers, the new name is based on their parent group name.

    If multiple layers would be renamed to the same name (e.g., they are in
    the same group, or multiple layers are empty), a geometry type suffix is
    appended to differentiate them.

    Returns:
        A tuple containing the rename plan, a list of skipped layer names, and a
        list of layer names that could not be found in the layer tree.
    """
    project: QgsProject = PluginContext.project()
    root: QgsLayerTree | None = project.layerTreeRoot()
    if root is None:
        raise_runtime_error("No Layer Tree is available.")

    layers_to_process: list[QgsMapLayer] = get_selected_layers()

    # Using defaultdict to group layers by their prospective new name
    potential_renames: defaultdict[str, list[QgsMapLayer]] = defaultdict(list)
    skipped_layers: list[str] = []

    log_debug(f"Renaming {len(layers_to_process)} layers...")
    for layer in layers_to_process:
        node: QgsLayerTreeLayer | None = root.findLayer(layer.id())

        # If the layer is not in the layer tree, skip it.
        if not node:
            skipped_layers.append(layer.name())
            log_debug(
                f"'{layer.name()}' → Rename → Skipped because not in layer tree.",
                Qgis.Warning,
            )
            continue

        # If a vector layer is empty, skip it.
        if isinstance(layer, QgsVectorLayer) and layer.featureCount() == 0:
            skipped_layers.append(layer.name())
            log_debug(
                f"'{layer.name()}' → Rename → Skipped because empty.", Qgis.Warning
            )
            continue

        # If the layer is not in a group, skip it.
        parent: QgsLayerTreeNode | None = node.parent()
        raw_group_name: str = parent.name() if parent else ""
        if not isinstance(parent, QgsLayerTreeGroup) or not raw_group_name:
            skipped_layers.append(layer.name())
            log_debug(
                f"'{layer.name()}' → Rename → Skipped because not in a group.",
                Qgis.Warning,
            )
            continue

        new_name_base: str = fix_layer_name(raw_group_name)
        if not new_name_base:
            skipped_layers.append(layer.name())
            log_debug(
                f"'{layer.name()}' → Rename → Skipped because invalid name.",
                Qgis.Warning,
            )
            continue

        potential_renames[new_name_base].append(layer)

    # Build the final rename plan, handling name collisions
    rename_plan: list = build_rename_plan(potential_renames)

    return rename_plan, skipped_layers


def build_rename_plan(
    potential_renames: defaultdict[str, list[QgsMapLayer]],
) -> list[tuple[QgsMapLayer, str, str]]:
    """Build a list of rename operations, handling potential name collisions.

    This function processes a dictionary where keys are potential new layer names
    and values are lists of layers that would be renamed to that key. If a key
    maps to multiple layers (a name collision), it appends a geometry-specific
    suffix to each layer's new name to ensure uniqueness. If a layer's current
    name already matches the proposed new name, it is excluded from the plan.

    Args:
        potential_renames: A dictionary grouping layers by their proposed new
            base name.

    Returns:
        list[tuple[QgsMapLayer, str, str]]: A list of tuples, where each tuple
            contains the layer object, its original name, and its proposed new
            name. This list represents the final, conflict-resolved rename plan.
    """
    rename_plan: list[tuple[QgsMapLayer, str, str]] = []
    for new_name_base, layers in potential_renames.items():
        if len(layers) > 1:
            log_debug(
                f"Name collision detected for '{new_name_base}'. Adding suffixes..."
            )
            for layer in layers:
                suffix: str = (
                    "" if layer.featureCount() == 0 else geometry_type_suffix(layer)
                )
                final_new_name: str = f"{new_name_base}{suffix}"
                if layer.name() != final_new_name:
                    rename_plan.append((layer, layer.name(), final_new_name))
        else:  # No collision
            layer: QgsMapLayer = layers[0]
            if layer.name() != new_name_base:
                rename_plan.append((layer, layer.name(), new_name_base))
    return rename_plan


def execute_rename_plan(
    rename_plan: list[tuple[QgsMapLayer, str, str]],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Execute the renaming of layers and record the changes for undo.

    This function iterates through the rename_plan, renaming each layer
    to its new name. If a rename operation fails (e.g., due to a duplicate
    name), it catches the RuntimeError and records the failure.

    Args:
        rename_plan: A list of tuples, each containing (layer, old_name, new_name).

    Returns:
        tuple: A tuple containing:
            - A list of failed rename operations in the format
              (old_name, new_name, error_message).
            - A list of successful rename operations for the undo stack
              in the format [layer_id, old_name, new_name].
    """
    failed_renames: list = []
    successful_renames: list[tuple[str, str, str]] = []

    for layer, old_name, new_layer_name in rename_plan:
        try:
            layer.setName(new_layer_name)
            # On success, record the change for the undo stack.
            successful_renames.append((layer.id(), old_name, new_layer_name))
        except RuntimeError as e:  # noqa: PERF203
            # If setName fails, the layer name is unchanged.
            failed_renames.append((old_name, new_layer_name, str(e)))

    if failed_renames:
        log_debug(
            f"Failed to rename {len(failed_renames)} layers: {failed_renames}",
            Qgis.Warning,
        )

    return failed_renames, successful_renames


def geometry_type_suffix(layer: QgsMapLayer) -> str:
    """Get a short suffix for the geometry type of a layer.

    Args:
        layer: The layer to get the geometry type suffix for.

    Returns:
        str: A string containing the geometry type suffix.
    """
    if not isinstance(layer, QgsVectorLayer):
        return ""
    if layer.name() == "polylines" or layer.name().endswith(" - pl"):
        return " - pl"

    geom_type: Qgis.GeometryType = QgsWkbTypes.geometryType(layer.wkbType())
    geom_display_string: str = QgsWkbTypes.geometryDisplayString(geom_type)

    return f" - {GEOMETRY_SUFFIX_MAP.get(geom_type, geom_display_string)}"


def rename_layers() -> None:
    """Orchestrate the renaming of selected layers to their parent group names.

    Prepares a rename plan, executes it, records the successful renames for potential
    undo, and presents a summary of the operation to the user.
    """
    rename_plan, skipped_layers = prepare_rename_plan()

    failed_renames, successful_renames = execute_rename_plan(rename_plan)

    successful_count: int = len(rename_plan) - len(failed_renames)

    if successful_renames:
        project: QgsProject = PluginContext.project()
        # Store the list of successful renames in the project file.
        # The list is stored as a JSON string.
        project.writeEntry(
            "UTEC_Layer_Tools", "last_rename", json.dumps(successful_renames)
        )

    action_tr: str = QCoreApplication.translate("log_summary", "Renamed")
    log_summary_message(
        successes=successful_count,
        skipped=skipped_layers,
        failures=failed_renames,
        action=action_tr,
    )


def undo_rename_layers() -> None:
    """Revert the last renaming operation.

    Reads the last rename history from the project, attempts to revert the
    names of the affected layers, and reports the results.
    """
    project: QgsProject = PluginContext.project()
    last_rename_json, found = project.readEntry("UTEC_Layer_Tools", "last_rename", "")

    if not found or not last_rename_json:
        log_debug("No rename operation found in history to undo.", Qgis.Warning)
        return

    try:
        last_rename: list[tuple[str, str, str]] = json.loads(last_rename_json)
    except json.JSONDecodeError:
        log_debug("Could not parse rename history.", Qgis.Critical)
        return

    successful_undos: int = 0
    failed_undos: list = []

    for layer_id, old_name, new_name in last_rename:
        layer: QgsMapLayer | None = project.mapLayer(layer_id)
        if not layer:
            failed_undos.append(
                (new_name, old_name, "Original layer not found in project.")
            )
            continue

        # Check if the layer name is still what we set it to.
        # If the user renamed it again, we shouldn't force an undo.
        if layer.name() != new_name:
            failed_undos.append(
                (
                    new_name,
                    old_name,
                    f"Layer was renamed to '{layer.name()}' since last operation.",
                )
            )
            continue

        try:
            layer.setName(old_name)
            successful_undos += 1
        except RuntimeError as e:
            failed_undos.append((new_name, old_name, str(e)))

    # Clear the history after a successful undo to prevent multiple undos.
    if successful_undos > 0:
        project.removeEntry("UTEC_Layer_Tools", "last_rename")

    action_tr: str = QCoreApplication.translate("log_summary", "Rename reverted")
    log_summary_message(
        successes=successful_undos, failures=failed_undos, action=action_tr
    )
