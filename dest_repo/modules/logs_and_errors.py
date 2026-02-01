"""Module: logs_and_errors.py

This module contains logging functions and custom error classes.
"""

import inspect
from pathlib import Path
from types import FrameType
from typing import NoReturn

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication

from .constants import Issue

LOG_TAG: str = "Plugin: UTEC Layer Tools"
LEVEL_ICON: dict[Qgis.MessageLevel, str] = {
    Qgis.Success: "🎉",
    Qgis.Info: "💡",
    Qgis.Warning: "💥",
    Qgis.Critical: "💀",
}


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
    prefix: str | None = None,
) -> None:
    """Log a debug message.

    Logs a message to the QGIS message log, prepending an icon and appending
    the filename and line number of the caller.

    Args:
        message: The message to log.
        level: The QGIS message level.
            (Qgis.Success, Qgis.Info, Qgis.Warning or Qgis.Critical)
            Defaults to Qgis.Info.
        file_line_number: An optional string to append to the message.
            Defaults to the filename and line number of the caller.
        icon: An optional icon string to prepend to the message. If None,
            a default icon based on `msg_level` will be used.
        prefix: An optional prefix string to prepend to the message.

    Returns:
        None
    """
    file_line_number = file_line_number or file_line(inspect.currentframe())

    icon = icon or LEVEL_ICON[level]
    message = f"{icon} {prefix or ''} {message}{file_line_number}"

    QgsMessageLog.logMessage(f"{message}", LOG_TAG, level=level)


def show_message(
    message: str, level: Qgis.MessageLevel = Qgis.Critical, duration: int = 0
) -> None:
    """Display a message in the QGIS message bar.

    This helper function standardizes error handling by ensuring that a critical
    error is logged and displayed to the user.

    Args:
        message: The error message to display and include in the exception.
        level: The QGIS message level (Warning, Critical, etc.).
            Defaults to Qgis.Critical.
        duration: The duration of the message in seconds (default: 0 = until closed).
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
            f"→ Message not displayed in message bar."
        )


def log_summary_message(
    processed: int,
    skipped: list[Issue] | None = None,
    errors: list[Issue] | None = None,
) -> None:
    """Generate a summary message for the user based on operation results.

    This function constructs a user-friendly message summarizing the outcome
    of a plugin operation (e.g., renaming, moving layers). It handles different
    result types (successes, skips, failures, not found) and pluralization
    to create grammatically correct and informative feedback.

    Args:
        processed: The total number of layers processed.
        skipped: A list of issues that occurred during the operation.
        errors: A list of errors that occurred during the operation.
    """

    # fmt: off
    # ruff: noqa: E501
    s_message: str = QCoreApplication.translate("log_summary", "{amount} layers processed. (skipped actions: {skipped} / errors: {errors})").format(amount=processed, skipped = len(skipped or []), errors = len(errors or []))
    protocol: str = QCoreApplication.translate("log_summary", " → For more inforation on skipped actions and errors, see the plugin log.")  
    # fmt: on

    l_message: str = s_message
    debug_level: Qgis.MessageLevel = Qgis.Success

    if skipped or errors:
        s_message = f"{s_message} {protocol}"
    if skipped:
        debug_level = Qgis.Info
        l_message = (
            f"{l_message}\nSkipped:\n{'\n'.join([str(issue) for issue in skipped])}"
        )
    if errors:
        debug_level = Qgis.Warning
        l_message = (
            f"{l_message}\nErrors:\n{'\n'.join([str(issue) for issue in errors])}"
        )

    log_debug(l_message, debug_level)
    show_message(s_message, debug_level, duration=10)


class CustomRuntimeError(Exception):
    """Custom exception for runtime errors in the plugin."""


class CustomUserError(Exception):
    """Custom exception for user-related errors in the plugin."""


def raise_runtime_error(error_msg: str) -> NoReturn:
    """Log a critical error, display it, and raise a CustomRuntimeError.

    Args:
        error_msg: The error message to be displayed and raised.

    Raises:
        CustomRuntimeError: The raised exception with the error message.
    """
    file_line_number: str = file_line(inspect.currentframe())
    error_msg = f"{error_msg}{file_line_number}"
    log_msg: str = f"{LEVEL_ICON[Qgis.Critical]} {error_msg}"
    QgsMessageLog.logMessage(f"{log_msg}", LOG_TAG, level=Qgis.Critical)

    show_message(error_msg)
    raise CustomRuntimeError(error_msg)


def raise_user_error(error_msg: str) -> NoReturn:
    """Log a user-facing warning, display it, and raise a CustomUserError.

    Args:
        error_msg: The error message to be displayed and raised.

    Raises:
        CustomUserError: The raised exception with the error message.
    """
    file_line_number: str = file_line(inspect.currentframe())
    log_msg: str = f"{LEVEL_ICON[Qgis.Warning]} {error_msg}{file_line_number}"
    QgsMessageLog.logMessage(f"{log_msg}", LOG_TAG, level=Qgis.Warning)

    show_message(error_msg, level=Qgis.Warning)
    raise CustomUserError(error_msg)
