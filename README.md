# huy-work

Configuration, agent skills, and tooling setup for corporate communication workflows and QA Automation.

## Repository Contents

- **skills/**: Agent skills for message harvesting, search, activity digests, and work management:
  - `chat`: Microsoft Teams and Zalo Web harvester, SQLite store, and digest generator.
  - `mail`: Outlook Web and Gmail reader, search, and action-item digest generator.
  - `work-tracker`: Daily planning, in-day task checkpoints, blocker tracking, standup reporting, and next-day rollover.
  - `summary-table`: Concise tabular reporting for test runs, inventories, and decision-making.
- **mcp/**: Model Context Protocol setup guides:
  - `browserctl.md`: Installation and configuration guide for `browserctl` MCP.
- **config/**:
  - `profile.md`: Global developer and QA automation persona instructions.

## Prerequisites

- Python 3.8+
- Node.js 18+ (for browserctl MCP)
- Google Chrome (or Chromium browser) with `browserctl` extension and local bridge daemon running on port 8765
