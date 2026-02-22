# PR: Add MCP integration, daemon mode, and managed run (Modes 2 & 3)

## Summary

This PR extends cord from a standalone CLI tool (Mode 1) into a fully MCP-integrated system with two new modes of operation:

- **Mode 2 (MCP Integration):** Claude Code acts as the root agent, calling cord's MCP tools directly (`init_tree`, `spawn`, `complete`). A background `cord daemon` launches child agents.
- **Mode 3 (Managed Run):** A single `run_tree()` MCP call launches an autonomous agent tree with a background daemon. Claude Code supervises — monitoring with `read_tree()` and intervening with `pause`/`stop`/`modify`/`spawn` as needed.

### Key changes

- **`init_tree()` / `run_tree()` MCP tools** — bootstrap coordination trees from within Claude Code
- **`cord daemon` CLI command** — watches `.cord/cord.db` and launches child agents; `--launch-root` flag for Mode 3
- **`read_logs()` MCP tool** — inspect agent stdout/stderr for debugging
- **Per-agent logging** — each agent's output saved to `.cord/agents/{id}.stdout.log` / `.stderr.log`
- **Tool call logging** — optional `--log-tools` flag writes JSONL to `.cord/tools.log`
- **`--project` fix in child MCP configs** — points to cord source root so `uv run` resolves correctly
- **`--allowedTools` made opt-in** — child agents now inherit global MCP servers instead of being restricted
- **`stdin=subprocess.DEVNULL`** — prevents daemon and agent subprocesses from consuming stdin

### Files changed (7 files, +850 / -65)

| File | Change |
|------|--------|
| `src/cord/mcp/server.py` | New `init_tree`, `run_tree`, `read_logs` tools; tool call logging; `@logged` decorator; agent_id guard |
| `src/cord/cli.py` | Add `cord daemon` command with `--launch-root`, `--log-tools` flags |
| `src/cord/runtime/engine.py` | `run_daemon()` method; skip-root-synthesis logic; per-agent log directory |
| `src/cord/runtime/dispatcher.py` | `--project` fix; log-to-file support; `stdin=DEVNULL`; opt-in `--allowedTools` |
| `src/cord/runtime/process_manager.py` | Read agent stdout from log files instead of PIPE |
| `USAGE.md` | Comprehensive guide for all three modes with setup, workflow, and tool reference |
| `CLAUDE.md` | Project context file for Claude Code integration |

## Test plan

- [ ] `cord run "simple goal"` still works (Mode 1 regression)
- [ ] MCP server starts cleanly: `uv run --project /path/to/cord cord-mcp-server`
- [ ] Mode 2: `init_tree()` → `cord daemon &` → `spawn()` → children launch and complete
- [ ] Mode 3: `run_tree("goal")` → daemon starts → tree completes autonomously
- [ ] `read_logs("#2")` returns agent output after completion
- [ ] `--log-tools` produces `.cord/tools.log` with JSONL entries
- [ ] Agent subprocesses don't hang waiting for stdin
