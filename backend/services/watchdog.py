"""Self-termination watchdog — monitors parent process and shuts down when it exits.

The watchdog runs as a daemon thread that polls the parent process (Tauri shell)
every 5 seconds. If the parent process is gone, it waits a 10-second grace period
and checks again before initiating shutdown. This prevents zombie sidecar processes
when the Tauri window is closed.
"""

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

# Polling interval in seconds
_POLL_INTERVAL = 5

# Grace period before shutdown in seconds
_GRACE_PERIOD = 10


def _is_process_alive(pid: int) -> bool:
    """Check if a process is alive by sending signal 0.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists and is reachable.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it —
        # still alive from our perspective.
        return True
    except OSError:
        return False


def _watchdog_loop(parent_pid: int) -> None:
    """Main watchdog loop — polls parent process and initiates shutdown on death.

    Args:
        parent_pid: PID of the parent process to monitor.
    """
    logger.info("Watchdog started, monitoring parent PID %d", parent_pid)

    while True:
        time.sleep(_POLL_INTERVAL)

        if _is_process_alive(parent_pid):
            continue

        logger.warning("Parent process %d not found, entering grace period", parent_pid)
        time.sleep(_GRACE_PERIOD)

        if _is_process_alive(parent_pid):
            logger.info("Parent process %d reappeared after grace period", parent_pid)
            continue

        logger.warning("Parent process %d confirmed dead, shutting down", parent_pid)
        # Give in-flight requests a moment to complete
        time.sleep(1)
        os._exit(0)


def start_watchdog(parent_pid: int) -> threading.Thread:
    """Start the watchdog thread.

    Args:
        parent_pid: PID of the parent process to monitor.

    Returns:
        The watchdog thread (daemon, already started).
    """
    thread = threading.Thread(
        target=_watchdog_loop,
        args=(parent_pid,),
        name="watchdog",
        daemon=True,
    )
    thread.start()
    return thread


def parse_parent_pid() -> int | None:
    """Parse --parent-pid from sys.argv.

    Returns:
        Parent PID as int, or None if not provided.
    """
    try:
        idx = sys.argv.index("--parent-pid")
        if idx + 1 < len(sys.argv):
            return int(sys.argv[idx + 1])
    except (ValueError, IndexError):
        pass
    return None
