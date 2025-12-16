"""MCP server connection management."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool

from .config import Config, ServerConfig

# Connection timeout in seconds
CONNECTION_TIMEOUT = 30


@dataclass
class ServerConnection:
    """Represents an active connection to an MCP server."""

    name: str
    session: ClientSession
    tools: list[Tool] = field(default_factory=list)


@dataclass
class ToolInfo:
    """Lightweight tool information for caching and search."""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "server": self.server,
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolInfo":
        """Create from dictionary."""
        return cls(
            server=data["server"],
            name=data["name"],
            description=data["description"],
            input_schema=data.get("inputSchema", {}),
        )


class ConnectionManager:
    """Manages lazy connections to MCP servers."""

    def __init__(self, config: Config):
        self.config = config
        self._connections: dict[str, ServerConnection] = {}

    def get_server_config(self, server_name: str) -> ServerConfig:
        """Get server configuration by name."""
        if server_name not in self.config.servers:
            available = ", ".join(sorted(self.config.servers.keys()))
            raise ValueError(
                f"Server '{server_name}' not found.\n\n"
                f"Available servers: {available}\n\n"
                f"Check your config file at: {self.config.config_path}"
            )
        return self.config.servers[server_name]

    @asynccontextmanager
    async def connect(self, server_name: str):
        """Connect to an MCP server and yield the session.

        This is a context manager that handles connection lifecycle.
        """
        server_config = self.get_server_config(server_name)

        # Build environment with resolved variables
        env = {**os.environ, **server_config.get_resolved_env()}

        # Check for missing required env vars
        for key, value in server_config.env.items():
            if value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                if not os.environ.get(env_var):
                    raise ValueError(
                        f"Missing required environment variable: {env_var}\n\n"
                        f"The '{server_name}' server requires {env_var} to be set.\n\n"
                        f"To fix this:\n"
                        f"1. Add {env_var}=your_value to your .env file\n"
                        f"2. Or set it in your environment: export {env_var}=your_value\n\n"
                        f"Searched .env locations:\n"
                        f"  ./.env\n"
                        f"  ~/.claude/.env"
                    )

        server_params = StdioServerParameters(
            command=server_config.command,
            args=server_config.args,
            env=env,
        )

        try:
            async with asyncio.timeout(CONNECTION_TIMEOUT):
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        yield session
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Connection to '{server_name}' timed out after {CONNECTION_TIMEOUT}s.\n\n"
                f"The server may be slow to start or unresponsive.\n\n"
                f"Command: {server_config.command} {' '.join(server_config.args)}\n\n"
                f"Try running the command manually to debug."
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Could not start '{server_name}' server.\n\n"
                f"Command not found: {server_config.command}\n\n"
                f"Make sure the MCP server is installed:\n"
                f"  - For uvx: uv tool install {server_config.args[0] if server_config.args else 'package-name'}\n"
                f"  - For npx: npm install -g {server_config.args[1] if len(server_config.args) > 1 else 'package-name'}"
            ) from e

    async def list_tools(self, server_name: str) -> list[ToolInfo]:
        """List all tools from a specific server."""
        async with self.connect(server_name) as session:
            result = await session.list_tools()
            return [
                ToolInfo(
                    server=server_name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                )
                for tool in result.tools
            ]

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Call a tool on a specific server."""
        async with self.connect(server_name) as session:
            result = await session.call_tool(tool_name, arguments)
            return result

