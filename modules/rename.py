"""Module: rename.py

This module contains the function for renaming layers in a QGIS project based
on their group names.
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

    layer: QgsMapLayer | None = None
    old_name: str | None = None
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
    suffix to each layer's new name to differentiate layers with different
    geometry types. If a layer's current
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


def prepare_rename_plan() -> ActionResults[list[Rename]]:
    """Prepare a plan to rename selected layers based on their parent group.

    The new name is based on the layer's parent group name.

    If multiple layers would be renamed to the same name (e.g., they are in
    the same group), a geometry type suffix is
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
    potential_renames: ActionResults[list[Rename]] = ActionResults([])

    log_debug(f"Rename → Renaming {len(layers_to_process)} layers...")
    for layer in layers_to_process:
        node: QgsLayerTreeLayer | None = root.findLayer(layer.id())
        old_name: str = layer.name()
        potential_renames.processed.append(old_name)

        # If the layer is not in the layer tree, skip it.
        if not node:
            log_debug(
                f"Rename → '{old_name}' → Error: layer not in layer tree.",
                Qgis.Warning,
            )
            potential_renames.errors.append(Issue(old_name, "not in layer tree"))
            continue

        parent: QgsLayerTreeNode | None = node.parent()
        raw_group_name: str = parent.name() if parent else ""

        # If the layer is not in a group, skip it.
        if not isinstance(parent, QgsLayerTreeGroup) or not raw_group_name:
            log_debug(
                f"Rename → '{old_name}' → Skipped because not in a group.",
                Qgis.Warning,
            )
            potential_renames.skips.append(Issue(old_name, "not in a group"))
            continue

        new_name: str = fix_layer_name(raw_group_name)
        if not new_name:
            log_debug(
                f"Rename → '{old_name}' → Skipped because invalid name.",
                Qgis.Warning,
            )
            potential_renames.errors.append(Issue(old_name, "invalid name"))
            continue

        potential_renames.result.append(Rename(layer, old_name, new_name))

    return ActionResults(
        result=handle_name_collisions(potential_renames.result),
        processed=potential_renames.processed,
        skips=potential_renames.skips,
        errors=potential_renames.errors,
    )


def execute_rename_plan(
    rename_plan: list[Rename],
) -> ActionResults[list[tuple[str, str, str]]]:
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
    # results.result stores successful renames as tuple for the json string.
    results: ActionResults[list[tuple[str, str, str]]] = ActionResults([])
    for rename in rename_plan:
        if rename.old_name:
            results.processed.append(rename.old_name)

        if (
            rename.error
            or not rename.layer
            or not rename.old_name
            or not rename.new_name
        ):
            results.errors.append(Issue(rename.old_name or "", rename.error or ""))
            continue

        if rename.skip:
            results.skips.append(Issue(rename.old_name, rename.skip))
            continue

        try:
            rename.layer.setName(rename.new_name)
            # On success, record the change for the undo stack.
            results.result.append((rename.layer.id(), rename.old_name, rename.new_name))
            results.successes.append(rename.old_name)
        except RuntimeError as e:
            # If setName fails, the layer name is unchanged.
            results.errors.append(Issue(rename.old_name, str(e)))

    if results.skips or results.errors:
        fails: int = len(results.skips) + len(results.errors)
        log_debug(
            f"Rename → Failed to rename {fails} layers.\n"
            f"Skips: {results.skips} / Errors: {results.errors})",
            Qgis.Warning,
        )

    return results


def rename_layers() -> ActionResults[None]:
    """Orchestrate the renaming of selected layers to their parent group names.

    Prepares a rename plan, executes it, records the successful renames for potential
    undo, and returns the results of the operation.

    Returns:
        ActionResults: The results of the rename operation.
    """
    prep: ActionResults[list[Rename]] = prepare_rename_plan()
    renamed: ActionResults[list[tuple[str, str, str]]] = execute_rename_plan(
        prep.result
    )

    # Store the list of successful renames in the project file
    # for the undo fuction of the plugin. (stored as a JSON string)
    if renamed.result:
        project: QgsProject = PluginContext.project()
        project.writeEntry(
            "UTEC_Layer_Tools", "last_rename", json.dumps(renamed.result)
        )

    return ActionResults(
        result=None,
        processed=renamed.processed,
        skips=renamed.skips,
        errors=renamed.errors,
    )


def undo_rename_layers() -> ActionResults[list[Rename]]:
    """Revert the last renaming operation.

    Reads the last rename history from the project, attempts to revert the
    names of the affected layers, and returns the results.

    Returns:
        ActionResults: The results of the undo operation.
    """
    project: QgsProject = PluginContext.project()
    rename_cache: tuple[str, bool | None] = project.readEntry(
        "UTEC_Layer_Tools", "last_rename", ""
    )
    last_rename_json: str = rename_cache[0]
    found: bool | None = rename_cache[1]

    if not found or not last_rename_json:
        log_debug("Rename → No rename operation found to undo.", Qgis.Warning)
        raise_runtime_error("No rename operation found to undo.")

    try:
        last_renames: list[tuple[str, str, str]] = json.loads(last_rename_json)
    except json.JSONDecodeError:
        log_debug("Rename → Could not parse rename history.", Qgis.Critical)
        raise_runtime_error("Could not parse rename history.")

    results: ActionResults[list[Rename]] = ActionResults([])
    for layer_id, old_name, new_name in last_renames:
        results.processed.append(new_name)

        layer: QgsMapLayer | None = project.mapLayer(layer_id)
        if not layer:
            results.errors.append(
                Issue(
                    new_name,
                    f"Layer '{new_name}' (old name'{old_name}') not found in project.",
                )
            )
            continue

        # Check if the layer name is still what we set it to.
        # If the user renamed it again, we shouldn't force an undo.
        if layer.name() != new_name:
            results.skips.append(
                Issue(
                    old_name,
                    f"Layer was manually renamed to '{layer.name()}' "
                    "since last operation and will not be reverted.",
                )
            )
            continue

        try:
            layer.setName(old_name)
            results.result.append(Rename(layer, new_name, old_name))
            results.successes.append(new_name)
        except RuntimeError as e:
            results.errors.append(Issue(new_name, str(e)))

    # Clear the history after a successful undo to prevent multiple undos.
    if results.successes or results.skips:
        project.removeEntry("UTEC_Layer_Tools", "last_rename")

    return results
