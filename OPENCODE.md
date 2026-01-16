# OpenCode Instructions for MCP Launchpad

When you need to use MCP tools, use the `mcpl` CLI tool via bash.

## Workflow

1. **Search for tools** across all MCP servers:
   ```bash
   mcpl search "query"
   ```

2. **Get tool details** (required parameters):
   ```bash
   mcpl inspect <server> <tool>
   ```

3. **Execute a tool**:
   ```bash
   mcpl call <server> <tool> '{"param": "value"}'
   ```

4. **List configured servers**:
   ```bash
   mcpl list
   ```

## Examples

Search for GitHub issues tools:
```bash
mcpl search "github issues"
```

List tools for a specific server:
```bash
mcpl list github
```

Call a tool:
```bash
mcpl call github list_issues '{"owner": "anthropics", "repo": "claude-code"}'
```

Get full tool schema with example:
```bash
mcpl inspect github list_issues --example
```

## Tips

- Always search first: `mcpl search "your query"`
- Use `mcpl inspect` to see required parameters
- Use `mcpl verify` to test server connections
- Use JSON mode for programmatic access: `mcpl --json search "query"`
- Use `mcpl session status` to check daemon and server connections
- If mcpl is not available, use: `uv tool run mcpl <command>`
