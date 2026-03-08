"""Tests for self-termination watchdog."""

import os
import sys
from unittest.mock import patch

from backend.services.watchdog import _is_process_alive, parse_parent_pid


class TestIsProcessAlive:
    """Tests for _is_process_alive()."""

    def test_current_process_is_alive(self) -> None:
        assert _is_process_alive(os.getpid()) is True

    def test_nonexistent_pid(self) -> None:
        # Use a very high PID that almost certainly doesn't exist
        assert _is_process_alive(999999999) is False

    def test_pid_zero_permission_error(self) -> None:
        # PID 0 may raise PermissionError on some systems
        result = _is_process_alive(0)
        assert isinstance(result, bool)


class TestParseParentPid:
    """Tests for parse_parent_pid()."""

    def test_returns_pid_when_present(self) -> None:
        with patch.object(sys, "argv", ["main.py", "--parent-pid", "12345"]):
            result = parse_parent_pid()
            assert result == 12345

    def test_returns_none_when_not_present(self) -> None:
        with patch.object(sys, "argv", ["main.py"]):
            result = parse_parent_pid()
            assert result is None

    def test_returns_none_when_no_value(self) -> None:
        with patch.object(sys, "argv", ["main.py", "--parent-pid"]):
            result = parse_parent_pid()
            assert result is None

    def test_returns_none_on_invalid_value(self) -> None:
        with patch.object(sys, "argv", ["main.py", "--parent-pid", "not_a_number"]):
            result = parse_parent_pid()
            assert result is None

    def test_works_with_other_args(self) -> None:
        with patch.object(
            sys, "argv", ["main.py", "--port", "8420", "--parent-pid", "42", "--debug"]
        ):
            result = parse_parent_pid()
            assert result == 42
