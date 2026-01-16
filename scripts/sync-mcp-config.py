#!/usr/bin/env python3
"""Sync MCP config between Claude Code (mcp.json) and OpenCode (opencode.jsonc) formats."""

import json
import sys
from pathlib import Path


def convert_to_opencode(mcp_config: dict) -> dict:
    """Convert mcp.json format to opencode.jsonc format."""
    opencode_config = {
        "$schema": "https://opencode.ai/config.json",
        "model": "anthropic/claude-sonnet-4-5",
        "small_model": "anthropic/claude-haiku-4-5",
        "theme": "opencode",
        "mcp": {},
    }

    for name, server in mcp_config.get("mcpServers", {}).items():
        opencode_server = {"enabled": True}

        if "url" in server:
            opencode_server["type"] = "remote"
            opencode_server["url"] = server["url"]
            if "headers" in server:
                opencode_server["headers"] = {
                    k: v.replace("${", "{env:").replace("}", "}")
                    for k, v in server["headers"].items()
                }
            if "oauth" in server:
                opencode_server["oauth"] = server["oauth"]
        else:
            opencode_server["type"] = "local"
            command = server.get("command", "")
            args = server.get("args", [])
            if command and args:
                opencode_server["command"] = [command] + args
            elif command:
                opencode_server["command"] = [command]
            elif args:
                opencode_server["command"] = args

        if "env" in server:
            opencode_server["environment"] = {
                k: v.replace("${", "{env:").replace("}", "}") for k, v in server["env"].items()
            }

        if "timeout" in server:
            opencode_server["timeout"] = server["timeout"]

        opencode_config["mcp"][name] = opencode_server

    return opencode_config


def convert_to_mcp(opencode_config: dict) -> dict:
    """Convert opencode.jsonc format to mcp.json format."""
    mcp_config = {"mcpServers": {}}

    for name, server in opencode_config.get("mcp", {}).items():
        mcp_server = {}

        if server.get("type") == "remote":
            mcp_server["type"] = "http"
            mcp_server["url"] = server.get("url", "")
            if "headers" in server:
                mcp_server["headers"] = {
                    k: v.replace("{env:", "${").replace("}", "}")
                    for k, v in server["headers"].items()
                }
            if "oauth" in server:
                mcp_server["oauth"] = server["oauth"]
        else:
            command = server.get("command", [])
            if command:
                mcp_server["command"] = command[0]
                mcp_server["args"] = command[1:] if len(command) > 1 else []

        if "environment" in server:
            mcp_server["env"] = {
                k: v.replace("{env:", "${").replace("}", "}")
                for k, v in server["environment"].items()
            }

        mcp_config["mcpServers"][name] = mcp_server

    return mcp_config


def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []

    if "--to-mcp" in args:
        opencode_path = Path("opencode.jsonc")
        mcp_path = Path("mcp.json")

        if not opencode_path.exists():
            print("Error: opencode.jsonc not found", file=sys.stderr)
            sys.exit(1)

        with open(opencode_path) as f:
            opencode_config = json.load(f)

        mcp_config = convert_to_mcp(opencode_config)

        with open(mcp_path, "w") as f:
            json.dump(mcp_config, f, indent=2)

        print(f"Synced {mcp_path} from {opencode_path}")
    else:
        mcp_path = Path("mcp.json")
        opencode_path = Path("opencode.jsonc")

        if not mcp_path.exists():
            print("Error: mcp.json not found", file=sys.stderr)
            sys.exit(1)

        with open(mcp_path) as f:
            mcp_config = json.load(f)

        opencode_config = convert_to_opencode(mcp_config)

        with open(opencode_path, "w") as f:
            json.dump(opencode_config, f, indent=2)

        print(f"Synced {opencode_path} from {mcp_path}")


if __name__ == "__main__":
    main()
