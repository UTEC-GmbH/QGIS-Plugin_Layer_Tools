"""Module: logs_and_errors.py

This module contains logging functions and custom error classes.
"""

import inspect
from pathlib import Path
from types import FrameType
from typing import NoReturn

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication

LEVEL_ICON: dict[Qgis.MessageLevel, str] = {
    Qgis.Success: "🎉",
    Qgis.Info: "💡",
    Qgis.Warning: "💥",
    Qgis.Critical: "💀",
}

LOG_TAG: str = "Plugin: UTEC Layer Tools"


def file_line(frame: FrameType | None) -> str:
    """Return the filename and line number of the caller.

    This function inspects the call stack to determine the file and line number
    from which `log_debug` or `log_and_show_error` was called.

    Args:
        frame: The current frame object,
            typically obtained via `inspect.currentframe()`.

    Returns:
        A string formatted as " (filename: line_number)" or an empty string if
        the frame information is not available.
    """

    if frame and frame.f_back:
        filename: str = Path(frame.f_back.f_code.co_filename).name
        lineno: int = frame.f_back.f_lineno
        return f" [{filename}: {lineno}]"
    return ""


def log_debug(
    message: str,
    level: Qgis.MessageLevel = Qgis.Info,
    file_line_number: str | None = None,
    icon: str | None = None,
) -> None:
    """Log a debug message.

    Logs a message to the QGIS message log, prepending an icon and appending
    the filename and line number of the caller.

    Args:
        message: The message to log.
        level: The QGIS message level (Success, Info, Warning, Critical).
            Defaults to Qgis.Info.
        file_line_number: An optional string to append to the message.
            Defaults to the filename and line number of the caller.
        icon: An optional icon string to prepend to the message. If None,
            a default icon based on `msg_level` will be used.

    Returns:
        None
    """

    file_line_number = file_line_number or file_line(inspect.currentframe())

    icon = icon or LEVEL_ICON[level]
    message = f"{icon} {message}{file_line_number}"

    QgsMessageLog.logMessage(f"{message}", LOG_TAG, level=level)


def show_message(
    message: str, level: Qgis.MessageLevel = Qgis.Critical, duration: int = 0
) -> None:
    """Display a message in the QGIS message bar.

    This helper function standardizes error handling by ensuring that a critical
    error is logged and displayed to the user.

    :param error_msg: The error message to display and include in the exception.
    :param level: The QGIS message level (Warning, Critical, etc.).
    :param duration: The duration of the message in seconds (default: 0 = until closed)
    :return: None
    """
    # pylint: disable=import-outside-toplevel
    from .context import PluginContext  # noqa: PLC0415

    if msg_bar := PluginContext.message_bar():
        msg_bar.clearWidgets()
        msg_bar.pushMessage(
            f"{LEVEL_ICON[level]} {message}", level=level, duration=duration
        )
    else:
        QgsMessageLog.logMessage(
            f"{LEVEL_ICON[Qgis.Warning]} message bar not available! "
            f"→ Error not displayed in message bar."
        )


def log_summary_message(
    successes: int = 0,
    skipped: list | None = None,
    failures: list | None = None,
    action: str = "Operation",
) -> None:
    """Generate a summary message for the user based on operation results.

    This function constructs a user-friendly message summarizing the outcome
    of a plugin operation (e.g., renaming, moving layers). It handles different
    result types (successes, skips, failures, not found) and pluralization
    to create grammatically correct and informative feedback.

    :param plugin: The QGIS plugin interface for interacting with QGIS.
    :param successes: The number of successful operations.
    :param skipped: A list of layer names that were skipped.
    :param failures: A list of tuples detailing failed operations,
                     (e.g., (old_name, new_name, error_message)).
    :param not_found: A list of layer names that could not be found.
    :param action: A string describing the action performed (e.g., "Renamed", "Copied").
    :returns: A tuple containing the summary message (str) and the message level (int).
    """

    layers_processed: int = (
        successes
        + (len(skipped) if skipped else 0)
        + (len(failures) if failures else 0)
    )

    # fmt: off
    message_parts: list[str] = [
        QCoreApplication.translate("log_summary", "{amount} Layers processed.").format(amount=layers_processed) # noqa: E501
    ]
    # fmt: on
    debug_level: Qgis.MessageLevel = Qgis.Success

    if successes:
        # fmt: off
        msg_part: str = QCoreApplication.translate("log_summary", "{action} {successes} layer(s).").format(action=action.lower(), successes=successes)  # noqa: E501
        # fmt: on
        message_parts.append(msg_part)

    if skipped:
        # fmt: off
        msg_part: str = QCoreApplication.translate("log_summary", "Skipped {num_skipped} layer(s).").format(num_skipped=len(skipped))  # noqa: E501
        # fmt: on
        debug_level = Qgis.Info
        message_parts.append(msg_part)
        for skipped_layer in skipped:
            log_debug(f"Skipped layer '{skipped_layer}'", debug_level)

    if failures:
        # fmt: off
        msg_part: str = QCoreApplication.translate("log_summary", "Failed to {action} {num_failures} layer(s).").format(action=action.lower(), num_failures=len(failures))  # noqa: E501
        # fmt: on
        debug_level = Qgis.Warning
        message_parts.append(msg_part)
        for failure in failures:
            log_debug(f"Failed to {action} {failure[0]}: {failure[1]}", debug_level)

    if not message_parts:  # If no operations were reported
        # fmt: off
        msg_part: str = QCoreApplication.translate("log_summary", "No layers processed or all selected layers already have the desired state.")  # noqa: E501
        # fmt: on
        debug_level = Qgis.Info
        message_parts.append(msg_part)

    full_message: str = " ".join(message_parts)

    log_debug(full_message, debug_level)
    show_message(full_message, debug_level, duration=10)


class CustomRuntimeError(Exception):
    """Custom exception for runtime errors in the plugin."""


class CustomUserError(Exception):
    """Custom exception for user-related errors in the plugin."""


def raise_runtime_error(error_msg: str) -> NoReturn:
    """Log a critical error, display it, and raise a CustomRuntimeError."""

    file_line_number: str = file_line(inspect.currentframe())
    error_msg = f"{error_msg}{file_line_number}"
    log_msg: str = f"{LEVEL_ICON[Qgis.Critical]} {error_msg}"
    QgsMessageLog.logMessage(f"{log_msg}", LOG_TAG, level=Qgis.Critical)

    show_message(error_msg)
    raise CustomRuntimeError(error_msg)


def raise_user_error(error_msg: str) -> NoReturn:
    """Log a user-facing warning, display it, and raise a CustomUserError."""

    file_line_number: str = file_line(inspect.currentframe())
    log_msg: str = f"{LEVEL_ICON[Qgis.Warning]} {error_msg}{file_line_number}"
    QgsMessageLog.logMessage(f"{log_msg}", LOG_TAG, level=Qgis.Warning)

    show_message(error_msg, level=Qgis.Warning)
    raise CustomUserError(error_msg)
