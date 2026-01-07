"""Module: functions_rename.py

This module contains the function for renaming and moving layers
in a QGIS project based on their group names.
"""

import contextlib
import json
import re
from dataclasses import dataclass
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

from .constants import GEOMETRY_SUFFIX_MAP, ActionResults, Issue
from .context import PluginContext
from .general import get_selected_layers, raise_runtime_error
from .logs_and_errors import log_debug

if TYPE_CHECKING:
    from qgis.core import QgsLayerTree, QgsLayerTreeNode


@dataclass
class Rename:
    """A dataclass for representing a rename plan for a layer.

    Attributes:
        layer (QgsMapLayer | None): The layer to be renamed.
        old_name (str | None): The current name of the layer.
        new_name (str | None): The proposed new name for the layer.
        skip (str | None): A reason for skipping the rename operation.
        error (str | None): An error message if the rename operation fails.
    """

    layer: QgsMapLayer | None
    old_name: str | None
    new_name: str | None = None
    skip: str | None = None
    error: str | None = None


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


def handle_name_collisions(potential_renames: list[Rename]) -> list[Rename]:
    """Build a list of rename operations, handling potential name collisions.

    This function processes a list of potential renames. If multiple layers
    target the same new name (a name collision), it appends a geometry-specific
    suffix to each layer's new name to ensure uniqueness. If a layer's current
    name already matches the proposed new name, it is excluded from the plan.

    Args:
        potential_renames (list[Rename]): A list of Rename objects representing
            potential rename operations.

    Returns:
        list[Rename]: A list of Rename objects representing the final,
            conflict-resolved rename plan.
    """
    # Starting with layers that don't need to be renamed (saving the error messages)
    rename_plan: list[Rename] = [ren for ren in potential_renames if not ren.new_name]

    # Then checking for name collisions
    for name in {pot.new_name for pot in potential_renames if pot.new_name}:
        layers: list[QgsMapLayer] = [
            pot.layer for pot in potential_renames if pot.layer and pot.new_name == name
        ]
        if len(layers) > 1:
            log_debug(
                f"Rename → Name collision detected for '{name}'. Adding suffixes..."
            )
            for layer in layers:
                suffix: str = (
                    "" if layer.featureCount() == 0 else geometry_type_suffix(layer)
                )
                final_new_name: str = f"{name}{suffix}"
                if layer.name() != final_new_name:
                    rename_plan.append(Rename(layer, layer.name(), final_new_name))

        # Finally adding layers that need to be renamed and don't have a collision
        else:
            layer: QgsMapLayer = layers[0]
            if layer.name() != name:
                rename_plan.append(Rename(layer, layer.name(), name))

    return rename_plan


def prepare_rename_plan() -> ActionResults:
    """Prepare a plan to rename selected layers based on their parent group.

    Empty vector layers are planned to be renamed to 'empty layer'. For other
    layers, the new name is based on their parent group name.

    If multiple layers would be renamed to the same name (e.g., they are in
    the same group, or multiple layers are empty), a geometry type suffix is
    appended to differentiate them.

    Returns:
        ActionResults: An object containing the rename plan (in .result),
            processed layers, skipped layers, and errors.
    """
    project: QgsProject = PluginContext.project()
    root: QgsLayerTree | None = project.layerTreeRoot()
    if root is None:
        raise_runtime_error("No Layer Tree is available.")

    layers_to_process: list[QgsMapLayer] = get_selected_layers()
    potential_renames: list[Rename] = []

    log_debug(f"Rename → Renaming {len(layers_to_process)} layers...")
    for layer in layers_to_process:
        node: QgsLayerTreeLayer | None = root.findLayer(layer.id())
        old_name: str = layer.name()

        # If the layer is not in the layer tree, skip it.
        if not node:
            log_debug(
                f"Rename → '{old_name}' → Error: layer not in layer tree.",
                Qgis.Warning,
            )
            potential_renames.append(Rename(layer, old_name, error="not in layer tree"))
            continue

        parent: QgsLayerTreeNode | None = node.parent()
        raw_group_name: str = parent.name() if parent else ""

        # If the layer is not in a group, skip it.
        if not isinstance(parent, QgsLayerTreeGroup) or not raw_group_name:
            log_debug(
                f"Rename → '{old_name}' → Skipped because not in a group.",
                Qgis.Warning,
            )
            potential_renames.append(Rename(layer, old_name, skip="not in a group"))
            continue

        new_name: str = fix_layer_name(raw_group_name)
        if not new_name:
            log_debug(
                f"Rename → '{old_name}' → Skipped because invalid name.",
                Qgis.Warning,
            )
            potential_renames.append(Rename(layer, old_name, error="invalid name"))
            continue

        potential_renames.append(Rename(layer, old_name, new_name))

    rename_plan: list[Rename] = handle_name_collisions(potential_renames)

    return ActionResults(
        result=rename_plan,
        processed=[ren.old_name for ren in rename_plan if ren.old_name],
        skips=[Issue(s.old_name, s.skip) for s in rename_plan if s.skip and s.old_name],
        errors=[
            Issue(e.old_name, e.error) for e in rename_plan if e.error and e.old_name
        ],
    )


def execute_rename_plan(rename_plan: list[Rename]) -> ActionResults:
    """Execute the renaming of layers and record the changes for undo.

    This function iterates through the rename_plan, renaming each layer
    to its new name. If a rename operation fails (e.g., due to a duplicate
    name), it catches the RuntimeError and records the failure.

    Args:
        rename_plan (list[Rename]): A list of Rename objects containing the
            details for each rename operation.

    Returns:
        ActionResults: An object containing the results of the execution,
            including successful renames (for the undo stack), skips, and errors.
    """
    fails: list[Rename] = []
    successful_renames: list[Rename] = []

    for rename in rename_plan:
        if rename.skip or rename.error or not rename.layer:
            fails.append(rename)
            continue
        try:
            rename.layer.setName(rename.new_name)
            # On success, record the change for the undo stack.
            successful_renames.append(rename)
        except RuntimeError as e:
            # If setName fails, the layer name is unchanged.
            fails.append(Rename(*rename, error=str(e)))

    if fails:
        log_debug(
            f"Rename → Failed to rename {len(fails)} layers: {fails}",
            Qgis.Warning,
        )

    return ActionResults(
        result=successful_renames,
        successes=[s.new_name for s in successful_renames if s.new_name],
        skips=[Issue(f.old_name, f.skip) for f in fails if f.skip and f.old_name],
        errors=[Issue(f.old_name, f.error) for f in fails if f.error and f.old_name],
    )


def rename_layers() -> ActionResults:
    """Orchestrate the renaming of selected layers to their parent group names.

    Prepares a rename plan, executes it, records the successful renames for potential
    undo, and presents a summary of the operation to the user.

    Returns:
        ActionResults: The results of the rename operation.
    """
    prep: ActionResults = prepare_rename_plan()
    renamed: ActionResults = execute_rename_plan(prep.result)

    # Store the list of successful renames in the project file.
    # The list is stored as a JSON string.
    if renamed.successes:
        successful_renames: list[tuple[str, str, str]] = [
            (ren.layer.id(), ren.old_name, ren.new_name) for ren in renamed.result
        ]
        project: QgsProject = PluginContext.project()
        project.writeEntry(
            "UTEC_Layer_Tools", "last_rename", json.dumps(successful_renames)
        )

    return renamed


def undo_rename_layers() -> ActionResults:
    """Revert the last renaming operation.

    Reads the last rename history from the project, attempts to revert the
    names of the affected layers, and reports the results.

    Returns:
        ActionResults: The results of the undo operation.
    """
    project: QgsProject = PluginContext.project()
    last_rename_json, found = project.readEntry("UTEC_Layer_Tools", "last_rename", "")

    if not found or not last_rename_json:
        log_debug("Rename → No rename operation found to undo.", Qgis.Warning)
        return ActionResults("Error: No rename operation found to undo.")
    try:
        last_renames: list[tuple[str, str, str]] = json.loads(last_rename_json)
    except json.JSONDecodeError:
        log_debug("Rename → Could not parse rename history.", Qgis.Critical)
        return ActionResults("Error: Could not parse rename history.")

    successful_undos: list[Rename] = []
    fails: list[Rename] = []
    processed: list[str] = []

    for layer_id, old_name, new_name in last_renames:
        processed.append(new_name)
        layer: QgsMapLayer | None = project.mapLayer(layer_id)
        if not layer:
            fails.append(
                Rename(
                    None,
                    new_name,
                    error=f"Original layer ('{old_name}') not found in project.",
                )
            )
            continue

        # Check if the layer name is still what we set it to.
        # If the user renamed it again, we shouldn't force an undo.
        if layer.name() != new_name:
            fails.append(
                Rename(
                    layer,
                    old_name,
                    new_name,
                    skip=f"Layer was renamed to '{layer.name()}' since last operation.",
                )
            )
            continue

        try:
            layer.setName(old_name)
            successful_undos.append(Rename(layer, new_name, old_name))
        except RuntimeError as e:
            fails.append(Rename(layer, new_name, old_name, error=str(e)))

    # Clear the history after a successful undo to prevent multiple undos.
    if successful_undos:
        project.removeEntry("UTEC_Layer_Tools", "last_rename")

    return ActionResults(
        result=successful_undos,
        processed=processed,
        successes=[s.old_name for s in successful_undos if s.old_name],
        skips=[Issue(f.old_name, f.skip) for f in fails if f.skip and f.old_name],
        errors=[Issue(f.old_name, f.error) for f in fails if f.error and f.old_name],
    )
