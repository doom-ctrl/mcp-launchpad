# MCP Launchpad

You have access to the MCP Launchpad (`mcpl`), a unified CLI for discovering and executing tools from multiple MCP servers. The user may configure and change their MCP configuration at any time. So if your task requires a tool or functionality outside of your current capabilities, it's critical that you always check the MCP Launchpad for available tools that may be useful.

## Quick Reference

```bash
# Show help
mcpl --help

# Find tools
mcpl search "<query>"                    # Search all tools (shows required params)
mcpl search "<query>" --first            # Top result with full details + example call
mcpl list                                # List all MCP servers
mcpl list <server>                       # List tools for a server

# Get tool details
mcpl inspect <server> <tool>             # Full schema
mcpl inspect <server> <tool> --example   # Schema + example call

# Execute tools
mcpl call <server> <tool> '{}'                        # No arguments
mcpl call <server> <tool> '{"param": "value"}'        # With arguments
```

## Workflow Pattern

1. **Search** → Find the right tool: `mcpl search "sentry errors"`
2. **Call** → Execute with required params shown in search results

For complex tools, use `--first` to get the example call:
```bash
mcpl search "sentry issues" --first
# Copy the example call and modify values
```

## Server-Specific Tips

### Sentry

When searching for Sentry errors/issues:
- `search_events` is more reliable for finding actual errors - use this first
- `search_issues` returns grouped issues but may miss recent errors
- Always pass `regionUrl` when provided by `find_organizations`

Example workflow:
```bash
mcpl call sentry find_organizations '{}'
mcpl call sentry search_events '{"organizationSlug": "my-org", "naturalLanguageQuery": "show all errors from last 7 days", "regionUrl": "https://us.sentry.io"}'
```
