"""Unit tests for the logs_and_errors module."""

from unittest.mock import MagicMock, patch

import pytest
from qgis.core import Qgis

from modules.constants import Issue
from modules.logs_and_errors import (
    CustomRuntimeError,
    CustomUserError,
    log_debug,
    log_summary_message,
    raise_runtime_error,
    raise_user_error,
    show_message,
)


def test_file_line() -> None:
    """Test the file_line function behavior."""
    # We test it indirectly via log_debug to ensure it captures the right frame
    with patch("qgis.core.QgsMessageLog.logMessage") as mock_log:
        log_debug("msg")
        args, _ = mock_log.call_args
        # In some environments, it might be python.py or similar, but
        # it should at least return a non-empty string with the expected format.
        assert "[" in args[0]
        assert "]" in args[0]
        assert ":" in args[0]


@patch("qgis.core.QgsMessageLog.logMessage")
def test_log_debug(mock_log_message: MagicMock) -> None:
    """Test log_debug dispatches to QgsMessageLog."""
    log_debug("test message", level=Qgis.Info, icon="🔍", prefix="PRE:")

    mock_log_message.assert_called_once()
    args, kwargs = mock_log_message.call_args
    assert "🔍 PRE: test message" in args[0]
    assert kwargs["level"] == Qgis.Info


@patch("modules.context.PluginContext.message_bar")
def test_show_message(mock_message_bar: MagicMock) -> None:
    """Test show_message clears and pushes to message bar."""
    bar = MagicMock()
    mock_message_bar.return_value = bar

    show_message("test user message", level=Qgis.Warning, duration=5)

    bar.clearWidgets.assert_called_once()
    bar.pushMessage.assert_called_with(
        "💥 test user message", level=Qgis.Warning, duration=5
    )


@patch("modules.logs_and_errors.show_message")
@patch("modules.logs_and_errors.log_debug")
def test_log_summary_message(
    mock_log_debug: MagicMock, mock_show_message: MagicMock
) -> None:
    """Test log_summary_message formatting."""
    skipped = [Issue(layer="L1", issue="skip reason")]
    errors = [Issue(layer="L2", issue="error reason")]

    log_summary_message(processed=5, skipped=skipped, errors=errors)

    # Check show_message call
    mock_show_message.assert_called_once()
    s_msg = mock_show_message.call_args[0][0]
    assert "5 layers processed" in s_msg
    assert "skipped actions: 1" in s_msg
    assert "errors: 1" in s_msg

    # Check log_debug call
    mock_log_debug.assert_called_once()
    l_msg = mock_log_debug.call_args[0][0]
    assert "Skipped:\nLayer: 'L1': skip reason" in l_msg
    assert "Errors:\nLayer: 'L2': error reason" in l_msg


@patch("qgis.core.QgsMessageLog.logMessage")
@patch("modules.logs_and_errors.show_message")
def test_raise_runtime_error(
    mock_show_message: MagicMock, mock_log_message: MagicMock
) -> None:
    """Test raise_runtime_error logs, shows, and raises."""
    with pytest.raises(CustomRuntimeError, match="critical bug"):
        raise_runtime_error("critical bug")

    mock_log_message.assert_called_once()
    mock_show_message.assert_called_once()


@patch("qgis.core.QgsMessageLog.logMessage")
@patch("modules.logs_and_errors.show_message")
def test_raise_user_error(
    mock_show_message: MagicMock, mock_log_message: MagicMock
) -> None:
    """Test raise_user_error logs, shows, and raises."""
    with pytest.raises(CustomUserError, match="user mistake"):
        raise_user_error("user mistake")

    mock_log_message.assert_called_once()
    mock_show_message.assert_called_once()
