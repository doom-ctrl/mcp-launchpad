"""Tests for error handling scenarios across all modules."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from mcp_launchpad.cli import main
from mcp_launchpad.config import Config, ServerConfig, load_config
from mcp_launchpad.connection import ConnectionManager, ToolInfo


class TestConfigErrors:
    """Test error handling in config module."""

    def test_no_config_file_anywhere(self, tmp_path: Path, monkeypatch):
        """Test error when no config file exists in any location."""
        monkeypatch.chdir(tmp_path)

        # Use explicit path that doesn't exist to ensure FileNotFoundError
        nonexistent = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError) as excinfo:
            load_config(config_path=nonexistent)

        error_msg = str(excinfo.value)
        assert "No MCP config file found" in error_msg
        assert ".mcp.json" in error_msg
        # Should include example config
        assert "mcpServers" in error_msg

    def test_config_file_empty(self, tmp_path: Path, monkeypatch):
        """Test handling of empty config file."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".mcp.json").write_text("")

        with pytest.raises(json.JSONDecodeError):
            load_config()

    def test_config_file_not_object(self, tmp_path: Path, monkeypatch):
        """Test handling of config that's not a JSON object."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".mcp.json").write_text('["array", "not", "object"]')

        # Should raise AttributeError since list doesn't have .get()
        with pytest.raises(AttributeError):
            load_config()

    def test_config_with_null_values(self, tmp_path: Path, monkeypatch):
        """Test handling of null values in config."""
        monkeypatch.chdir(tmp_path)
        config_data = {
            "mcpServers": {
                "test": {
                    "command": "python",
                    "args": None,
                    "env": None,
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(config_data))

        # Should handle None values gracefully
        config = load_config()
        assert config.servers["test"].args is None or config.servers["test"].args == []


class TestConnectionErrors:
    """Test error handling in connection module."""

    def test_server_not_in_config(self):
        """Test error when trying to connect to non-existent server."""
        config = Config(
            servers={"only-server": ServerConfig(name="only-server", command="test")},
            config_path=None,
            env_path=None,
        )
        manager = ConnectionManager(config)

        with pytest.raises(ValueError) as excinfo:
            manager.get_server_config("missing-server")

        error_msg = str(excinfo.value)
        assert "Server 'missing-server' not found" in error_msg
        assert "only-server" in error_msg  # Should list available servers

    def test_empty_server_list_error_message(self):
        """Test error message when no servers configured."""
        config = Config(servers={}, config_path=None, env_path=None)
        manager = ConnectionManager(config)

        with pytest.raises(ValueError) as excinfo:
            manager.get_server_config("any-server")

        error_msg = str(excinfo.value)
        assert "Server 'any-server' not found" in error_msg

    async def test_missing_required_env_var(self):
        """Test error when required environment variable is missing."""
        config = Config(
            servers={
                "needs-token": ServerConfig(
                    name="needs-token",
                    command="python",
                    args=["-m", "server"],
                    env={"API_TOKEN": "${DEFINITELY_NOT_SET_12345}"},
                )
            },
            config_path=None,
            env_path=None,
        )
        manager = ConnectionManager(config)

        # Ensure the env var is not set
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as excinfo:
                async with manager.connect("needs-token"):
                    pass

            error_msg = str(excinfo.value)
            assert "Missing required environment variable" in error_msg
            assert "DEFINITELY_NOT_SET_12345" in error_msg
            assert "needs-token" in error_msg

    async def test_command_not_found(self):
        """Test error when server command doesn't exist."""
        config = Config(
            servers={
                "bad-cmd": ServerConfig(
                    name="bad-cmd",
                    command="this_command_does_not_exist_xyz_123",
                    args=[],
                    env={},
                )
            },
            config_path=None,
            env_path=None,
        )
        manager = ConnectionManager(config)

        with pytest.raises(FileNotFoundError) as excinfo:
            async with manager.connect("bad-cmd"):
                pass

        error_msg = str(excinfo.value)
        assert "Could not start 'bad-cmd' server" in error_msg
        assert "Command not found" in error_msg


class TestCLIErrorDisplay:
    """Test that CLI displays errors appropriately."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_human_mode_error_display(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Test error is displayed in human-readable format."""
        monkeypatch.chdir(tmp_path)
        # Use explicit non-existent config to force error
        # Click returns exit code 2 for usage errors (like invalid path)
        nonexistent = tmp_path / "nonexistent.json"

        result = runner.invoke(main, ["--config", str(nonexistent), "list"])

        assert result.exit_code == 2  # Click usage error
        # Should have Error: prefix in human mode
        assert "Error" in result.output

    def test_json_mode_error_display(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Test error is displayed in JSON format for application errors."""
        monkeypatch.chdir(tmp_path)
        # Create a valid config but with a server that will fail
        config_data = {"mcpServers": {"test": {"command": "test"}}}
        (tmp_path / ".mcp.json").write_text(json.dumps(config_data))

        with patch("mcp_launchpad.cli.ToolCache") as MockCache:
            mock_cache = MagicMock()
            mock_cache.refresh = AsyncMock(side_effect=RuntimeError("Connection failed"))
            MockCache.return_value = mock_cache

            # Use --refresh to trigger the refresh path which will error
            result = runner.invoke(main, ["--json", "list", "--refresh"])

            assert result.exit_code == 1
            parsed = json.loads(result.output)
            assert parsed["success"] is False
            assert "error" in parsed
            assert "message" in parsed["error"]

    def test_json_error_includes_traceback(
        self, runner: CliRunner, tmp_path: Path, monkeypatch
    ):
        """Test JSON error includes traceback for debugging."""
        monkeypatch.chdir(tmp_path)
        # Create a valid config but with a server that will fail
        config_data = {"mcpServers": {"test": {"command": "test"}}}
        (tmp_path / ".mcp.json").write_text(json.dumps(config_data))

        with patch("mcp_launchpad.cli.ToolCache") as MockCache:
            mock_cache = MagicMock()
            mock_cache.refresh = AsyncMock(side_effect=RuntimeError("Connection failed"))
            MockCache.return_value = mock_cache

            # Use --refresh to trigger the refresh path which will error
            result = runner.invoke(main, ["--json", "list", "--refresh"])

            assert result.exit_code == 1
            parsed = json.loads(result.output)
            assert "traceback" in parsed["error"]

    def test_json_error_includes_type(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Test JSON error includes error type."""
        monkeypatch.chdir(tmp_path)
        # Create a valid config but with a server that will fail
        config_data = {"mcpServers": {"test": {"command": "test"}}}
        (tmp_path / ".mcp.json").write_text(json.dumps(config_data))

        with patch("mcp_launchpad.cli.ToolCache") as MockCache:
            mock_cache = MagicMock()
            mock_cache.refresh = AsyncMock(side_effect=RuntimeError("Connection failed"))
            MockCache.return_value = mock_cache

            # Use --refresh to trigger the refresh path which will error
            result = runner.invoke(main, ["--json", "list", "--refresh"])

            assert result.exit_code == 1
            parsed = json.loads(result.output)
            assert "type" in parsed["error"]


class TestCacheErrors:
    """Test error handling in cache module."""

    def test_cache_refresh_all_servers_fail(self, tmp_path: Path):
        """Test error when all servers fail during cache refresh."""
        from mcp_launchpad.cache import ToolCache

        config = Config(
            servers={
                "server1": ServerConfig(name="server1", command="cmd"),
                "server2": ServerConfig(name="server2", command="cmd"),
            },
            config_path=tmp_path / "config.json",
            env_path=None,
        )
        (tmp_path / "config.json").write_text("{}")

        cache = ToolCache(config)
        cache.cache_dir = tmp_path
        cache.index_path = tmp_path / "index.json"
        cache.metadata_path = tmp_path / "metadata.json"

        mock_manager = MagicMock()
        mock_manager.list_tools = AsyncMock(side_effect=RuntimeError("Connection failed"))

        with patch("mcp_launchpad.cache.ConnectionManager", return_value=mock_manager):
            with pytest.raises(RuntimeError) as excinfo:
                asyncio.run(cache.refresh(force=True))

            assert "Failed to connect to any servers" in str(excinfo.value)

    def test_cache_corrupted_index(self, tmp_path: Path):
        """Test handling of corrupted cache index file."""
        from mcp_launchpad.cache import ToolCache

        config = Config(
            servers={"test": ServerConfig(name="test", command="cmd")},
            config_path=tmp_path / "config.json",
            env_path=None,
        )
        (tmp_path / "config.json").write_text("{}")

        cache = ToolCache(config)
        cache.cache_dir = tmp_path
        cache.index_path = tmp_path / "index.json"
        cache.metadata_path = tmp_path / "metadata.json"

        # Write corrupted data
        cache.index_path.write_text("not valid json {{{")

        # Should return empty list, not crash
        tools = cache._load_tools()
        assert tools == []

    def test_cache_corrupted_metadata(self, tmp_path: Path):
        """Test handling of corrupted cache metadata file."""
        from mcp_launchpad.cache import ToolCache

        config = Config(
            servers={"test": ServerConfig(name="test", command="cmd")},
            config_path=tmp_path / "config.json",
            env_path=None,
        )
        (tmp_path / "config.json").write_text("{}")

        cache = ToolCache(config)
        cache.cache_dir = tmp_path
        cache.index_path = tmp_path / "index.json"
        cache.metadata_path = tmp_path / "metadata.json"

        # Write corrupted metadata
        cache.metadata_path.write_text("{invalid")

        # Should return None, not crash
        metadata = cache._load_metadata()
        assert metadata is None


class TestSearchErrors:
    """Test error handling in search module."""

    def test_invalid_regex_pattern(self):
        """Test error message for invalid regex."""
        from mcp_launchpad.search import ToolSearcher

        tools = [
            ToolInfo(
                server="test", name="test_tool", description="Test", input_schema={}
            )
        ]
        searcher = ToolSearcher(tools)

        with pytest.raises(ValueError) as excinfo:
            searcher.search_regex("[unclosed")

        assert "Invalid regex pattern" in str(excinfo.value)

    def test_search_empty_query(self):
        """Test search with empty query returns no results."""
        from mcp_launchpad.search import ToolSearcher

        tools = [
            ToolInfo(
                server="test", name="test_tool", description="Test", input_schema={}
            )
        ]
        searcher = ToolSearcher(tools)

        # BM25 with empty query
        results = searcher.search_bm25("")
        assert results == []


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_tool_with_empty_description(self):
        """Test tool with empty description."""
        tool = ToolInfo(
            server="test",
            name="no_desc",
            description="",
            input_schema={},
        )
        assert tool.description == ""
        from mcp_launchpad.search import build_search_text

        # Should not crash
        text = build_search_text(tool)
        assert "test" in text
        assert "no_desc" in text

    def test_tool_with_complex_schema(self):
        """Test tool with deeply nested schema."""
        tool = ToolInfo(
            server="test",
            name="complex",
            description="Complex tool",
            input_schema={
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {
                            "deep": {
                                "type": "array",
                                "items": {"type": "string"},
                            }
                        },
                    }
                },
                "required": ["nested"],
            },
        )
        # Should handle complex schema without crashing
        params = tool.get_required_params()
        assert params == ["nested"]
        example = tool.get_example_call()
        assert "mcpl call" in example

    def test_server_config_with_empty_command(self):
        """Test server config with empty command."""
        config = ServerConfig(name="empty", command="")
        assert config.command == ""

    def test_config_with_unicode_characters(self, tmp_path: Path, monkeypatch):
        """Test config with unicode in server names and values."""
        monkeypatch.chdir(tmp_path)

        config_data = {
            "mcpServers": {
                "test-üñíçödé": {
                    "command": "python",
                    "args": ["--name", "tëst"],
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(config_data, ensure_ascii=False))

        config = load_config()
        assert "test-üñíçödé" in config.servers

