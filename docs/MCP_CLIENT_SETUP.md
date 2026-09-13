# Connect an agent to Tarkka over MCP

This is recipe 3 from issue #198's five-minute adoption path: *give an AI agent a bounded evidence
backend through MCP.* It documents exact, copy-pasteable wiring for independent agent ecosystems.
Design rationale (progressive disclosure, token wallets, capability discovery) lives in
[`AGENT_INTERFACE.md`](AGENT_INTERFACE.md) and [`CONTEXT_EFFICIENCY.md`](CONTEXT_EFFICIENCY.md); this
document only covers connecting a client.

## What the server exposes

`tarkka-mcp` speaks MCP over stdio and registers only read-only, idempotent, closed-world tools:
`research_capabilities`, `research_operation_schema`, `research_get`, `research_expand`,
`research_compare`, `claim_lineage`, `document_manifest`, `document_sections`, `document_section`,
`document_replay`, and `retrieval_search`. No tool can mutate research state, and every response is
bounded by an explicit per-request token wallet rather than dumping full documents into context. It
reuses the same application services as the `tarkka` CLI, so anything ingested with `tarkka ingest`,
`tarkka workspace run`, or the [proof/replay walkthrough](QUICKSTART_PROOF_REPLAY.md) is immediately
visible to a connected agent.

## Prerequisites

Tarkka is not yet published to PyPI (see the README's license/release note), so install it from a
checkout:

```bash
git clone https://github.com/cbwinslow/Tarkka.git
cd Tarkka
uv sync --group dev --extra mcp   # or: python -m pip install -e '.[mcp]'
uv run tarkka-mcp --help          # confirms the console script resolves; stdio servers take no args
```

The server honors the same environment variables as the CLI:

- `TARKKA_HOME` — local state directory, defaults to `~/.tarkka`.
- `TARKKA_DOCUMENT_BACKEND` — `json` (dependency-free default) or `postgres`.
- `TARKKA_WORK_BACKEND` — `json` (default) or `postgres`.

Point every client at the same `TARKKA_HOME` you used to ingest content, or the agent will see an
empty workspace.

## Claude Code

Project-scoped (checked into `.mcp.json`, shared with a team):

```json
{
  "mcpServers": {
    "tarkka": {
      "command": "tarkka-mcp",
      "env": { "TARKKA_HOME": "/absolute/path/to/.tarkka" }
    }
  }
}
```

Or from the command line (personal, local scope):

```bash
claude mcp add --transport stdio tarkka -- tarkka-mcp
```

Verify with `/mcp` inside a Claude Code session; it should list `tarkka` as connected with the
tools above.

## Codex CLI

```bash
codex mcp add tarkka --command tarkka-mcp
```

Or edit `~/.codex/config.toml` (or a project `.codex/config.toml`) directly:

```toml
[mcp_servers.tarkka]
command = "tarkka-mcp"

[mcp_servers.tarkka.env]
TARKKA_HOME = "/absolute/path/to/.tarkka"
```

Verify with `codex mcp list`, or `/mcp` inside a session.

## Claude Desktop

Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`; Windows:
`%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "tarkka": {
      "command": "tarkka-mcp",
      "env": { "TARKKA_HOME": "/absolute/path/to/.tarkka" }
    }
  }
}
```

Restart Claude Desktop; the tool icon should list Tarkka's read-only research tools.

## Try it end to end

1. Run the [proof/replay walkthrough](QUICKSTART_PROOF_REPLAY.md) (or `tarkka ingest`/`tarkka
   workspace run` against your own source) with a fixed `TARKKA_HOME`.
2. Point one of the clients above at that same `TARKKA_HOME`.
3. Ask the agent to call `research_capabilities` first, then `research_get` on a `claim:<uuid>`
   handle it discovers — it should retrieve a bounded manifest/receipt rather than the full
   document, and can expand to exact evidence only when it needs to justify an answer.

If a tool call returns `backend_unavailable` or `not_found`, the client is either pointed at a
different `TARKKA_HOME` than the one you ingested into, or the referenced backend (e.g.
`TARKKA_DOCUMENT_BACKEND=postgres`) isn't configured identically for the CLI and the MCP client.
