"""Tests for connection module."""

import json
import os
from unittest.mock import patch

import pytest

from mcp_launchpad.config import Config, ServerConfig
from mcp_launchpad.connection import ConnectionManager, ToolInfo


class TestToolInfo:
    """Tests for ToolInfo dataclass."""

    def test_basic_creation(self):
        """Test creating a basic ToolInfo."""
        tool = ToolInfo(
            server="github",
            name="create_issue",
            description="Create a new issue",
            input_schema={"type": "object", "properties": {}},
        )
        assert tool.server == "github"
        assert tool.name == "create_issue"
        assert tool.description == "Create a new issue"

    def test_to_dict(self):
        """Test converting ToolInfo to dictionary."""
        tool = ToolInfo(
            server="github",
            name="create_issue",
            description="Create a new issue",
            input_schema={"type": "object", "properties": {}, "required": ["title"]},
        )
        d = tool.to_dict()
        assert d["server"] == "github"
        assert d["name"] == "create_issue"
        assert d["description"] == "Create a new issue"
        assert d["inputSchema"] == {
            "type": "object",
            "properties": {},
            "required": ["title"],
        }

    def test_from_dict(self):
        """Test creating ToolInfo from dictionary."""
        data = {
            "server": "sentry",
            "name": "search_issues",
            "description": "Search for issues",
            "inputSchema": {"type": "object", "required": ["query"]},
        }
        tool = ToolInfo.from_dict(data)
        assert tool.server == "sentry"
        assert tool.name == "search_issues"
        assert tool.description == "Search for issues"
        assert tool.input_schema == {"type": "object", "required": ["query"]}

    def test_from_dict_missing_schema(self):
        """Test creating ToolInfo when inputSchema is missing."""
        data = {
            "server": "test",
            "name": "test_tool",
            "description": "A test tool",
        }
        tool = ToolInfo.from_dict(data)
        assert tool.input_schema == {}

    def test_get_required_params(self):
        """Test extracting required parameters."""
        tool = ToolInfo(
            server="github",
            name="create_issue",
            description="Create issue",
            input_schema={
                "type": "object",
                "properties": {"owner": {}, "repo": {}, "title": {}},
                "required": ["owner", "repo", "title"],
            },
        )
        assert tool.get_required_params() == ["owner", "repo", "title"]

    def test_get_required_params_empty(self):
        """Test when no required params."""
        tool = ToolInfo(
            server="test",
            name="test_tool",
            description="Test",
            input_schema={"type": "object", "properties": {"optional": {}}},
        )
        assert tool.get_required_params() == []

    def test_get_params_summary(self):
        """Test getting params summary."""
        tool = ToolInfo(
            server="github",
            name="list_issues",
            description="List issues",
            input_schema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "state": {"type": "string"},
                    "labels": {"type": "array"},
                },
                "required": ["owner", "repo"],
            },
        )
        summary = tool.get_params_summary()
        assert "owner, repo" in summary
        assert "Optional:" in summary
        assert "state" in summary

    def test_get_params_summary_no_params(self):
        """Test params summary with no parameters."""
        tool = ToolInfo(
            server="test",
            name="no_params",
            description="No params tool",
            input_schema={"type": "object"},
        )
        assert tool.get_params_summary() == "No parameters"

    def test_get_example_call(self):
        """Test generating example CLI call."""
        tool = ToolInfo(
            server="github",
            name="create_issue",
            description="Create issue",
            input_schema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "count": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["owner", "count", "enabled"],
            },
        )
        example = tool.get_example_call()
        assert "mcpl call github create_issue" in example
        assert "<owner>" in example
        # Check the JSON is valid
        json_start = example.index("'") + 1
        json_end = example.rindex("'")
        parsed = json.loads(example[json_start:json_end])
        assert "owner" in parsed
        assert parsed["count"] == 0
        assert parsed["enabled"] is True


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    def test_get_server_config_exists(self, sample_config: Config):
        """Test getting an existing server config."""
        manager = ConnectionManager(sample_config)
        config = manager.get_server_config("test-server")
        assert config.name == "test-server"
        assert config.command == "python"

    def test_get_server_config_not_found(self, sample_config: Config):
        """Test getting a non-existent server config."""
        manager = ConnectionManager(sample_config)
        with pytest.raises(ValueError) as excinfo:
            manager.get_server_config("nonexistent")

        assert "Server 'nonexistent' not found" in str(excinfo.value)
        assert "Available servers: test-server" in str(excinfo.value)

    def test_get_server_config_lists_multiple_available(
        self, multi_server_config: Config
    ):
        """Test error message lists all available servers."""
        manager = ConnectionManager(multi_server_config)
        with pytest.raises(ValueError) as excinfo:
            manager.get_server_config("unknown")

        error_msg = str(excinfo.value)
        assert "github" in error_msg
        assert "sentry" in error_msg
        assert "slack" in error_msg


class TestConnectionManagerConnect:
    """Tests for ConnectionManager.connect method and error handling."""

    @pytest.fixture
    def manager_with_missing_env(self) -> ConnectionManager:
        """Create a manager with a server requiring missing env var."""
        config = Config(
            servers={
                "needs-env": ServerConfig(
                    name="needs-env",
                    command="python",
                    args=["-m", "server"],
                    env={"REQUIRED_TOKEN": "${MISSING_TOKEN}"},
                ),
            },
            config_path=None,
            env_path=None,
        )
        return ConnectionManager(config)

    async def test_connect_missing_env_var(
        self, manager_with_missing_env: ConnectionManager
    ):
        """Test connecting when required env var is missing."""
        # Clear the env var to ensure it's missing
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as excinfo:
                async with manager_with_missing_env.connect("needs-env"):
                    pass

            error_msg = str(excinfo.value)
            assert "Missing required environment variable: MISSING_TOKEN" in error_msg
            assert "needs-env" in error_msg

    async def test_connect_command_not_found(self, sample_config: Config):
        """Test connecting when command doesn't exist."""
        # Create config with nonexistent command
        config = Config(
            servers={
                "bad-cmd": ServerConfig(
                    name="bad-cmd",
                    command="nonexistent_command_12345",
                    args=[],
                    env={},
                ),
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
        assert "Command not found: nonexistent_command_12345" in error_msg

    async def test_connect_timeout(self, sample_config: Config):
        """Test connection timeout handling."""
        # Create config that will hang
        config = Config(
            servers={
                "slow-server": ServerConfig(
                    name="slow-server",
                    command="sleep",
                    args=["999"],
                    env={},
                ),
            },
            config_path=None,
            env_path=None,
        )
        manager = ConnectionManager(config)

        # Patch the timeout to be very short
        with patch("mcp_launchpad.connection.CONNECTION_TIMEOUT", 0.1):
            with pytest.raises(TimeoutError) as excinfo:
                async with manager.connect("slow-server"):
                    pass

            error_msg = str(excinfo.value)
            assert "timed out" in error_msg
            assert "slow-server" in error_msg


class TestConnectionManagerListTools:
    """Tests for ConnectionManager.list_tools method."""

    async def test_list_tools_server_not_found(self, sample_config: Config):
        """Test list_tools with non-existent server."""
        manager = ConnectionManager(sample_config)

        with pytest.raises(ValueError) as excinfo:
            await manager.list_tools("nonexistent")

        assert "Server 'nonexistent' not found" in str(excinfo.value)


class TestConnectionManagerCallTool:
    """Tests for ConnectionManager.call_tool method."""

    async def test_call_tool_server_not_found(self, sample_config: Config):
        """Test call_tool with non-existent server."""
        manager = ConnectionManager(sample_config)

        with pytest.raises(ValueError) as excinfo:
            await manager.call_tool("nonexistent", "some_tool", {})

        assert "Server 'nonexistent' not found" in str(excinfo.value)
