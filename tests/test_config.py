"""Tests for config module."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_launchpad.config import (
    Config,
    ServerConfig,
    find_config_file,
    find_env_file,
    load_config,
    parse_server_config,
)


class TestServerConfig:
    """Tests for ServerConfig dataclass."""

    def test_basic_creation(self):
        """Test creating a basic server config."""
        config = ServerConfig(
            name="test",
            command="python",
            args=["-m", "server"],
            env={"KEY": "value"},
        )
        assert config.name == "test"
        assert config.command == "python"
        assert config.args == ["-m", "server"]
        assert config.env == {"KEY": "value"}

    def test_default_values(self):
        """Test default values for optional fields."""
        config = ServerConfig(name="test", command="python")
        assert config.args == []
        assert config.env == {}

    def test_get_resolved_env_static_values(self):
        """Test resolving static env values."""
        config = ServerConfig(
            name="test",
            command="python",
            env={"STATIC_KEY": "static_value"},
        )
        resolved = config.get_resolved_env()
        assert resolved == {"STATIC_KEY": "static_value"}

    def test_get_resolved_env_variable_substitution(self):
        """Test resolving env variable references."""
        with patch.dict(os.environ, {"MY_TOKEN": "secret-token"}):
            config = ServerConfig(
                name="test",
                command="python",
                env={"TOKEN": "${MY_TOKEN}"},
            )
            resolved = config.get_resolved_env()
            assert resolved == {"TOKEN": "secret-token"}

    def test_get_resolved_env_missing_variable(self):
        """Test resolving missing env variable returns empty string."""
        # Ensure the variable is not set
        with patch.dict(os.environ, {}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                env={"TOKEN": "${NONEXISTENT_VAR}"},
            )
            resolved = config.get_resolved_env()
            assert resolved == {"TOKEN": ""}

    def test_get_resolved_env_mixed_values(self):
        """Test resolving mixed static and variable values."""
        with patch.dict(os.environ, {"VAR1": "value1"}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                env={
                    "STATIC": "static_value",
                    "DYNAMIC": "${VAR1}",
                    "MISSING": "${MISSING_VAR}",
                },
            )
            resolved = config.get_resolved_env()
            assert resolved == {
                "STATIC": "static_value",
                "DYNAMIC": "value1",
                "MISSING": "",
            }

    def test_get_resolved_env_partial_substitution(self):
        """Test resolving partial variable substitution in env values."""
        with patch.dict(os.environ, {"HOST": "localhost", "PORT": "8080"}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                env={
                    "URL": "http://${HOST}:${PORT}/api",
                    "PREFIX": "prefix_${HOST}",
                    "SUFFIX": "${PORT}_suffix",
                },
            )
            resolved = config.get_resolved_env()
            assert resolved == {
                "URL": "http://localhost:8080/api",
                "PREFIX": "prefix_localhost",
                "SUFFIX": "8080_suffix",
            }

    def test_get_resolved_args_static_values(self):
        """Test resolving static arg values."""
        config = ServerConfig(
            name="test",
            command="python",
            args=["-m", "server", "--port", "8080"],
        )
        resolved = config.get_resolved_args()
        assert resolved == ["-m", "server", "--port", "8080"]

    def test_get_resolved_args_variable_substitution(self):
        """Test resolving arg variable references."""
        with patch.dict(os.environ, {"MY_TOKEN": "secret-token"}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                args=["--token", "${MY_TOKEN}"],
            )
            resolved = config.get_resolved_args()
            assert resolved == ["--token", "secret-token"]

    def test_get_resolved_args_missing_variable(self):
        """Test resolving missing arg variable returns empty string."""
        with patch.dict(os.environ, {}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                args=["--token", "${NONEXISTENT_VAR}"],
            )
            resolved = config.get_resolved_args()
            assert resolved == ["--token", ""]

    def test_get_resolved_args_partial_substitution(self):
        """Test resolving partial variable substitution in args."""
        with patch.dict(os.environ, {"HOST": "localhost", "PORT": "8080"}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                args=[
                    "--url",
                    "http://${HOST}:${PORT}/api",
                    "--header",
                    "Authorization: Bearer ${TOKEN}",
                ],
            )
            resolved = config.get_resolved_args()
            assert resolved == [
                "--url",
                "http://localhost:8080/api",
                "--header",
                "Authorization: Bearer ",  # Missing TOKEN resolves to empty
            ]

    def test_get_resolved_args_mixed_values(self):
        """Test resolving mixed static and variable args."""
        with patch.dict(os.environ, {"TOKEN": "abc123"}, clear=True):
            config = ServerConfig(
                name="test",
                command="npx",
                args=[
                    "-y",
                    "@supabase/mcp-server",
                    "--access-token",
                    "${TOKEN}",
                ],
            )
            resolved = config.get_resolved_args()
            assert resolved == [
                "-y",
                "@supabase/mcp-server",
                "--access-token",
                "abc123",
            ]

    def test_get_resolved_env_remapped_variable(self):
        """Test remapping env var to different name for subprocess."""
        with patch.dict(os.environ, {"A_API_KEY": "secret123"}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                env={
                    "MY_API_KEY": "${A_API_KEY}",  # Remap A_API_KEY -> MY_API_KEY
                },
            )
            resolved = config.get_resolved_env()
            assert resolved == {"MY_API_KEY": "secret123"}

    def test_get_resolved_env_literal_without_braces(self):
        """Test that values without ${} are treated as literals."""
        with patch.dict(os.environ, {"A_API_KEY": "secret123"}, clear=True):
            config = ServerConfig(
                name="test",
                command="python",
                env={
                    "MY_API_KEY": "A_API_KEY",  # No ${} = literal string
                },
            )
            resolved = config.get_resolved_env()
            assert resolved == {"MY_API_KEY": "A_API_KEY"}  # Literal, not resolved


class TestFindConfigFile:
    """Tests for find_config_file function."""

    def test_explicit_path_exists(self, tmp_path: Path):
        """Test with explicit path that exists."""
        config_file = tmp_path / "custom.json"
        config_file.write_text("{}")
        result = find_config_file(config_file)
        assert result == config_file

    def test_explicit_path_not_exists(self, tmp_path: Path):
        """Test with explicit path that doesn't exist."""
        config_file = tmp_path / "nonexistent.json"
        result = find_config_file(config_file)
        assert result is None

    def test_no_config_file_found(self, tmp_path: Path, monkeypatch):
        """Test when no config file is found in search paths."""
        monkeypatch.chdir(tmp_path)
        result = find_config_file(None)
        # May find user-level config, so just check it doesn't raise
        assert result is None or result.exists()

    def test_project_level_config(self, tmp_path: Path, monkeypatch):
        """Test project-level .mcp.json is found."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / ".mcp.json"
        config_file.write_text("{}")
        result = find_config_file(None)
        # Compare resolved paths since function may return relative path
        assert result is not None
        assert result.resolve() == config_file.resolve()


class TestFindEnvFile:
    """Tests for find_env_file function."""

    def test_explicit_path_exists(self, tmp_path: Path):
        """Test with explicit path that exists."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value")
        result = find_env_file(env_file)
        assert result == env_file

    def test_explicit_path_not_exists(self, tmp_path: Path):
        """Test with explicit path that doesn't exist."""
        env_file = tmp_path / "nonexistent.env"
        result = find_env_file(env_file)
        assert result is None

    def test_project_level_env(self, tmp_path: Path, monkeypatch):
        """Test project-level .env is found."""
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value")
        result = find_env_file(None)
        # Compare resolved paths since function may return relative path
        assert result is not None
        assert result.resolve() == env_file.resolve()


class TestParseServerConfig:
    """Tests for parse_server_config function."""

    def test_full_config(self):
        """Test parsing a complete server config."""
        data = {
            "command": "uvx",
            "args": ["mcp-server-github"],
            "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        }
        config = parse_server_config("github", data)
        assert config.name == "github"
        assert config.command == "uvx"
        assert config.args == ["mcp-server-github"]
        assert config.env == {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}

    def test_minimal_config(self):
        """Test parsing with only required fields."""
        data = {"command": "python"}
        config = parse_server_config("minimal", data)
        assert config.name == "minimal"
        assert config.command == "python"
        assert config.args == []
        assert config.env == {}

    def test_missing_command(self):
        """Test parsing with missing command defaults to empty string."""
        data = {"args": ["some-arg"]}
        config = parse_server_config("no-command", data)
        assert config.command == ""
        assert config.args == ["some-arg"]


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(self, tmp_path: Path, monkeypatch):
        """Test loading a valid config file."""
        monkeypatch.chdir(tmp_path)

        config_data = {
            "mcpServers": {
                "github": {
                    "command": "uvx",
                    "args": ["mcp-server-github"],
                    "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
                },
                "slack": {
                    "command": "npx",
                    "args": ["-y", "@slack/mcp-server"],
                },
            }
        }
        config_file = tmp_path / ".mcp.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config()

        assert len(config.servers) == 2
        assert "github" in config.servers
        assert "slack" in config.servers
        assert config.servers["github"].command == "uvx"
        assert config.servers["slack"].args == ["-y", "@slack/mcp-server"]
        # Compare resolved paths since function may return relative path
        assert config.config_path is not None
        assert config.config_path.resolve() == config_file.resolve()

    def test_load_explicit_config_path(self, tmp_path: Path):
        """Test loading config from explicit path."""
        config_data = {"mcpServers": {"test": {"command": "python"}}}
        config_file = tmp_path / "custom-config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(config_path=config_file)

        assert len(config.servers) == 1
        assert "test" in config.servers
        assert config.config_path == config_file

    def test_config_not_found(self, tmp_path: Path, monkeypatch):
        """Test FileNotFoundError when no config file exists."""
        monkeypatch.chdir(tmp_path)
        # Use explicit path that doesn't exist to ensure FileNotFoundError
        nonexistent = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError) as excinfo:
            load_config(config_path=nonexistent)

        assert "No MCP config file found" in str(excinfo.value)

    def test_invalid_json_config(self, tmp_path: Path, monkeypatch):
        """Test JSONDecodeError for invalid JSON."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / ".mcp.json"
        config_file.write_text("{ not valid json }")

        with pytest.raises(json.JSONDecodeError):
            load_config()

    def test_empty_mcp_servers(self, tmp_path: Path, monkeypatch):
        """Test loading config with empty mcpServers."""
        monkeypatch.chdir(tmp_path)
        config_data = {"mcpServers": {}}
        config_file = tmp_path / ".mcp.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config()

        assert config.servers == {}

    def test_missing_mcp_servers_key(self, tmp_path: Path, monkeypatch):
        """Test loading config without mcpServers key."""
        monkeypatch.chdir(tmp_path)
        config_data = {"otherKey": "value"}
        config_file = tmp_path / ".mcp.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config()

        assert config.servers == {}

    def test_load_with_env_file(self, tmp_path: Path, monkeypatch):
        """Test loading config with .env file."""
        monkeypatch.chdir(tmp_path)

        # Create config
        config_data = {"mcpServers": {"test": {"command": "python"}}}
        config_file = tmp_path / ".mcp.json"
        config_file.write_text(json.dumps(config_data))

        # Create .env file
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=my_value")

        config = load_config()

        # Compare resolved paths since function may return relative path
        assert config.env_path is not None
        assert config.env_path.resolve() == env_file.resolve()
        # Verify env var was loaded
        assert os.environ.get("MY_VAR") == "my_value"

    def test_load_with_explicit_env_path(self, tmp_path: Path, monkeypatch):
        """Test loading config with explicit env file path."""
        monkeypatch.chdir(tmp_path)

        # Create config
        config_data = {"mcpServers": {"test": {"command": "python"}}}
        config_file = tmp_path / ".mcp.json"
        config_file.write_text(json.dumps(config_data))

        # Create custom env file
        custom_env = tmp_path / "custom.env"
        custom_env.write_text("CUSTOM_VAR=custom_value")

        config = load_config(env_path=custom_env)

        assert config.env_path == custom_env
        assert os.environ.get("CUSTOM_VAR") == "custom_value"

