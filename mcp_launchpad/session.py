"""Session client for communicating with the daemon."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import Config
from .ipc import IPCMessage, connect_to_daemon, read_message, write_message
from .platform import (
    IS_WINDOWS,
    get_log_file_path,
    get_pid_file_path,
    get_session_id,
    get_socket_path,
    is_process_alive,
)

# How long to wait for daemon to start (seconds) - configurable via env
DAEMON_START_TIMEOUT = int(os.environ.get("MCPL_DAEMON_START_TIMEOUT", "30"))

# How long to wait between connection attempts (seconds)
DAEMON_CONNECT_RETRY_DELAY = float(os.environ.get("MCPL_DAEMON_CONNECT_RETRY_DELAY", "0.2"))


class SessionClient:
    """Client for communicating with the session daemon."""

    def __init__(self, config: Config):
        self.config = config

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a tool via the daemon."""
        response = await self._send_request(
            IPCMessage(
                action="call_tool",
                payload={
                    "server": server_name,
                    "tool": tool_name,
                    "arguments": arguments,
                },
            )
        )
        return response.payload

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        """List tools from a server via the daemon."""
        response = await self._send_request(
            IPCMessage(action="list_tools", payload={"server": server_name})
        )
        tools: list[dict[str, Any]] = response.payload.get("tools", [])
        return tools

    async def get_status(self) -> dict[str, Any]:
        """Get daemon status."""
        response = await self._send_request(IPCMessage(action="status", payload={}))
        return response.payload

    async def shutdown(self) -> None:
        """Request daemon shutdown."""
        try:
            await self._send_request(IPCMessage(action="shutdown", payload={}))
        except Exception:
            pass  # Daemon may close connection before responding

    async def _send_request(self, message: IPCMessage) -> IPCMessage:
        """Send a request to the daemon and get the response."""
        # Ensure daemon is running
        await self._ensure_daemon_running()

        # Connect and send request
        connection = await connect_to_daemon()
        if not connection:
            raise RuntimeError("Failed to connect to daemon")

        reader, writer = connection
        try:
            await write_message(writer, message)
            response = await read_message(reader)

            if not response:
                raise RuntimeError("No response from daemon")

            if response.action == "error":
                raise RuntimeError(response.payload.get("error", "Unknown error"))

            return response
        finally:
            writer.close()
            await writer.wait_closed()

    async def _ensure_daemon_running(self) -> None:
        """Ensure the daemon is running, starting it if necessary."""
        if await self._is_daemon_running():
            return

        # Start the daemon
        await self._start_daemon()

        # Wait for daemon to be ready
        start_time = time.time()
        while time.time() - start_time < DAEMON_START_TIMEOUT:
            if await self._is_daemon_running():
                return
            await asyncio.sleep(DAEMON_CONNECT_RETRY_DELAY)

        # Daemon failed to start - provide helpful error message
        log_file = get_log_file_path()
        error_msg = f"Daemon failed to start within {DAEMON_START_TIMEOUT} seconds"

        # Try to read the last few lines of the log file for context
        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    if lines:
                        # Get last 10 lines (or fewer if file is smaller)
                        tail_lines = lines[-10:]
                        log_tail = "".join(tail_lines).strip()
                        error_msg += f"\n\nDaemon log (last lines from {log_file}):\n{log_tail}"
                    else:
                        error_msg += f"\n\nLog file is empty. Check {log_file} for details."
            except Exception:
                error_msg += f"\n\nCheck daemon log at: {log_file}"
        else:
            error_msg += f"\n\nLog file not found at: {log_file}"

        raise RuntimeError(error_msg)

    async def _is_daemon_running(self) -> bool:
        """Check if the daemon is currently running."""
        # Check PID file
        pid_file = get_pid_file_path()
        if not pid_file.exists():
            return False

        try:
            pid = int(pid_file.read_text().strip())
            if not is_process_alive(pid):
                # Stale PID file
                pid_file.unlink(missing_ok=True)
                return False
        except (ValueError, OSError):
            return False

        # Try to connect
        connection = await connect_to_daemon()
        if connection:
            reader, writer = connection
            writer.close()
            await writer.wait_closed()
            return True

        return False

    async def _start_daemon(self) -> None:
        """Start the daemon process."""
        # Build command to run daemon
        # Use the same Python interpreter and run the daemon module
        python_exe = sys.executable
        daemon_cmd = [python_exe, "-m", "mcp_launchpad.daemon"]

        # Add config path if we have one
        if self.config.config_path:
            daemon_cmd.extend(["--config", str(self.config.config_path)])

        # Ensure daemon uses the same session ID as client
        # This is critical so they use the same socket/pid/log file paths
        daemon_env = os.environ.copy()
        daemon_env["MCPL_SESSION_ID"] = get_session_id()

        # Open log file for daemon output
        log_file = get_log_file_path()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, "w")

        # Start as detached process
        if IS_WINDOWS:
            # Windows: Use CREATE_NEW_PROCESS_GROUP and DETACHED_PROCESS
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(
                daemon_cmd,
                env=daemon_env,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
            )
        else:
            # Unix: Use double-fork or nohup pattern
            subprocess.Popen(
                daemon_cmd,
                env=daemon_env,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

