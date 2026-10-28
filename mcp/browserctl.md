# browserctl MCP Setup Guide

`browserctl` is a browser automation MCP server and toolset that allows AI coding assistants (Claude Code, Antigravity, Cursor) to drive your existing, authenticated Chrome profile without relaunching or needing separate debugging sessions.

---

## 1. Architecture

```text
┌──────────────────────────────────────┐
│  AI Assistant (Claude / Antigravity) │
└──────────────────┬───────────────────┘
                   │ stdio (MCP protocol)
                   ▼
┌──────────────────────────────────────┐
│       browserctl-mcp (Node.js)       │
└──────────────────┬───────────────────┘
                   │ HTTP (port 8765)
                   ▼
┌──────────────────────────────────────┐
│       Bridge Daemon (localhost)      │
└──────────────────┬───────────────────┘
                   │ WebSocket
                   ▼
┌──────────────────────────────────────┐
│   Chrome Extension (Active Session)  │
└──────────────────────────────────────┘
```

---

## 2. Prerequisites

- **Node.js**: Version 18 or later (`node -v`).
- **Google Chrome** (or Chromium-based browser such as Brave, Edge).
- **browserctl Chrome Extension**: Installed in Developer Mode or via Chrome Web Store.
- **browserctl Bridge Daemon**: Running locally on port `8765`.

---

## 3. Registering the MCP Server

### Claude Code

Run the following command in terminal:

```bash
claude mcp add browserctl -s user -- npx -y -p browserctl-mcp browserctl-mcp
```

### Antigravity / Gemini CLI

Add to your global or project configuration:

```json
{
  "mcpServers": {
    "browserctl": {
      "command": "npx",
      "args": ["-y", "-p", "browserctl-mcp", "browserctl-mcp"],
      "env": {
        "BROWSERCTL_BRIDGE_URL": "http://127.0.0.1:8765"
      }
    }
  }
}
```

### Cursor

Add to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (workspace):

```json
{
  "mcpServers": {
    "browserctl": {
      "command": "npx",
      "args": ["-y", "-p", "browserctl-mcp", "browserctl-mcp"]
    }
  }
}
```

### VS Code (GitHub Copilot / MCP Extension)

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "browserctl": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "-p", "browserctl-mcp", "browserctl-mcp"]
    }
  }
}
```

---

## 4. Local Bridge Configuration

The bridge daemon connects the MCP server to the browser extension:

1. Start the bridge daemon (default port: `8765`):
   ```bash
   npx browserctl bridge
   ```
2. Verify the bridge is reachable:
   ```bash
   curl -s http://127.0.0.1:8765/status
   ```
3. In Chrome, ensure the browserctl extension icon indicates a connected status (green indicator).

---

## 5. Verification

In your agent session (Claude Code or Antigravity), verify connectivity by asking:
- "Check browserctl status"
- Or calling `browser_status` / `browser_tabs`.
