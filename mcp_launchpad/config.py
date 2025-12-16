"""Config discovery and loading for MCP Launchpad."""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _resolve_env_vars(value: str) -> str:
    """Resolve ${VAR} patterns in a string from environment variables.

    Handles:
    - Full replacement: "${VAR}" -> "value"
    - Partial replacement: "prefix_${VAR}_suffix" -> "prefix_value_suffix"
    - Multiple vars: "${VAR1}_${VAR2}" -> "value1_value2"
    - Missing vars resolve to empty string
    """
    if "${" not in value:
        return value

    result = value
    for match in re.finditer(r'\$\{([^}]+)\}', value):
        env_var = match.group(1)
        env_value = os.environ.get(env_var, "")
        result = result.replace(match.group(0), env_value)
    return result


@dataclass
class ServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    def get_resolved_env(self) -> dict[str, str]:
        """Resolve environment variables, expanding ${VAR} references."""
        return {key: _resolve_env_vars(value) for key, value in self.env.items()}

    def get_resolved_args(self) -> list[str]:
        """Resolve environment variables in args, expanding ${VAR} references."""
        return [_resolve_env_vars(arg) for arg in self.args]


@dataclass
class Config:
    """Complete MCP Launchpad configuration."""

    servers: dict[str, ServerConfig] = field(default_factory=dict)
    config_path: Path | None = None
    env_path: Path | None = None


# Config file search paths in priority order
CONFIG_SEARCH_PATHS = [
    Path(".mcp.json"),
    Path("mcp.json"),
    Path(".claude/mcp.json"),
    Path.home() / ".claude" / "mcp.json",
]

# Env file search paths in priority order
ENV_SEARCH_PATHS = [
    Path(".env"),
    Path.home() / ".claude" / ".env",
]


def find_config_file(explicit_path: Path | None = None) -> Path | None:
    """Find the MCP config file, checking project then user level."""
    if explicit_path:
        if explicit_path.exists():
            return explicit_path
        return None

    for path in CONFIG_SEARCH_PATHS:
        if path.exists():
            return path
    return None


def find_env_file(explicit_path: Path | None = None) -> Path | None:
    """Find the .env file, checking project then user level."""
    if explicit_path:
        if explicit_path.exists():
            return explicit_path
        return None

    for path in ENV_SEARCH_PATHS:
        if path.exists():
            return path
    return None


def parse_server_config(name: str, data: dict[str, Any]) -> ServerConfig:
    """Parse a server configuration from JSON data."""
    return ServerConfig(
        name=name,
        command=data.get("command", ""),
        args=data.get("args", []),
        env=data.get("env", {}),
    )


def load_config(
    config_path: Path | None = None,
    env_path: Path | None = None,
) -> Config:
    """Load MCP configuration from discovered or explicit paths.

    Args:
        config_path: Explicit path to config file (optional)
        env_path: Explicit path to .env file (optional)

    Returns:
        Config object with loaded servers

    Raises:
        FileNotFoundError: If no config file is found
        json.JSONDecodeError: If config file is invalid JSON
    """
    # Find and load .env file first
    env_file = find_env_file(env_path)
    if env_file:
        load_dotenv(env_file)

    # Find config file
    config_file = find_config_file(config_path)
    if not config_file:
        searched = ", ".join(str(p) for p in CONFIG_SEARCH_PATHS)
        raise FileNotFoundError(
            f"No MCP config file found.\n\n"
            f"Searched locations:\n"
            f"  {searched}\n\n"
            f"Create a config file with your MCP servers. Example:\n\n"
            f'{{\n  "mcpServers": {{\n'
            f'    "github": {{\n'
            f'      "command": "uvx",\n'
            f'      "args": ["mcp-server-github"],\n'
            f'      "env": {{"GITHUB_TOKEN": "${{GITHUB_TOKEN}}"}}\n'
            f"    }}\n  }}\n}}"
        )

    # Load and parse config
    with open(config_file) as f:
        data = json.load(f)

    servers = {}
    mcp_servers = data.get("mcpServers", {})
    for name, server_data in mcp_servers.items():
        servers[name] = parse_server_config(name, server_data)

    return Config(
        servers=servers,
        config_path=config_file,
        env_path=env_file,
    )

