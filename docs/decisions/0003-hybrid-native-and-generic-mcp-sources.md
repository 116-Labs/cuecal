# Hybrid sources: native adapters plus one generic MCP adapter

**Context:** Zoho Mail and Cliq are reachable through Zoho's MCP server (mcp.zoho.com), and any MCP server should be pluggable.

**Decision:** Native adapters for Gmail and Slack, plus one generic MCP-client adapter driven by a per-server mapping file (TOML/YAML). It supports stdio and streamable HTTP via the official `mcp` Python SDK.

**Consequences:** Adding an MCP-backed source normally means adding a mapping file, not code. Mappings must let users override Zoho tool names. `cuecal doctor` lists each server's tools and validates the mapping.
