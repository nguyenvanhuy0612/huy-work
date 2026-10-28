# huy-work

Configuration, agent skills, and tooling setup for corporate communication workflows and QA Automation.

## Repository Contents

- **skills/**: Agent skills for message harvesting, search, and activity digests:
  - `msteam`: Microsoft Teams discussion harvester, SQLite store, and digest generator.
  - `zalo`: Zalo Web message aggregator, SQLite store, and digest generator.
  - `outlook`: Outlook Web email reader, search, and action-item digest generator.
  - `summary-table`: Concise tabular reporting for test runs, inventories, and decision-making.
- **mcp/**: Model Context Protocol setup guides:
  - `browserctl.md`: Installation and configuration guide for `browserctl` MCP.
- **config/**:
  - `profile.md`: Global developer and QA automation persona instructions.

## Prerequisites

- Python 3.8+
- Node.js 18+ (for browserctl MCP)
- Google Chrome (or Chromium browser) with `browserctl` extension and local bridge daemon running on port 8765
