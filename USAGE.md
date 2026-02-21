# Cord Usage Guide

Cord coordinates trees of Claude Code agents. One goal in, multiple agents out — they decompose, parallelize, wait on dependencies, and synthesize.

Three modes of operation:

| | Mode 1: Standalone | Mode 2: MCP Integration | Mode 3: Managed Run |
|---|---|---|---|
| **How it starts** | `cord run "goal"` | `init_tree("goal")` + `cord daemon` | `run_tree("goal")` |
| **Root agent** | Claude subprocess | Claude Code (you) | Claude subprocess |
| **Who supervises** | Nobody | You | Claude Code |
| **Launches children** | Cord | `cord daemon` | `cord daemon --launch-root` |
| **Synthesizes results** | Automatic | You call `complete()` | Automatic |
| **MCP monitoring** | No | Yes | Yes |
| **Can intervene** | No | Yes | Yes |
| **Best for** | Fire-and-forget | Hands-on interactive | Supervised autonomy |

---

## Prerequisites (all modes)

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) — `claude` command available and authenticated
- Anthropic API key with sufficient credits

```bash
git clone https://github.com/kimjune01/cord.git
cd cord
uv sync
```

---

## Mode 1: Standalone (`cord run`)

Cord creates the root agent, launches everything, and manages the full lifecycle. No MCP setup needed.

### Setup

None beyond the prerequisites. Just run `cord` from any directory.

### Usage

```bash
# Simple goal
cord run "Analyze the pros and cons of Rust vs Go for CLI tools"

# From a planning doc
cord run plan.md

# With options
cord run "goal" --budget 5.0 --model opus --log-tools
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--budget` | 2.0 | Max USD per agent subprocess |
| `--model` | sonnet | Claude model (sonnet, opus, haiku) |
| `--log-tools` | off | Log all MCP tool calls to `.cord/tools.log` |

### What happens

1. Cord creates `.cord/cord.db` and root node `#1`
2. Root agent launches, decomposes the goal, spawns children via `spawn()`/`fork()`
3. Children execute (possibly in parallel, with dependency ordering)
4. When all children finish, root is relaunched with a synthesis prompt
5. Root synthesizes results and calls `complete()`
6. Cord exits

### Limitations

- No visibility into the tree while it runs (just a TUI status display)
- No way to intervene, pause, or redirect agents mid-run

---

## Mode 2: MCP Integration (Claude Code as root)

**You** (via Claude Code) are the root agent `#1`. You call cord's MCP tools directly to decompose work, spawn children, monitor progress, and synthesize results. `cord daemon` runs in the background to launch child processes.

### Setup

**Step 1: Add cord to your project's MCP config**

Create or edit `.claude/mcp.json` in your project directory:

```json
{
  "mcpServers": {
    "cord": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/cord",
        "cord-mcp-server"
      ]
    }
  }
}
```

Replace `/path/to/cord` with the absolute path to your cord clone (where `pyproject.toml` lives).

**Step 2: Restart Claude Code** to pick up the new MCP server.

That's it. The MCP server defaults to `.cord/cord.db` relative to your project's working directory. No `--agent-id` or `--db-path` flags needed.

### Workflow

**Step 1: Initialize the tree**

```
Call init_tree("Build a metabolomics analysis pipeline")
```

This creates `.cord/cord.db`, inserts the root node `#1`, and sets your session as agent `#1`. Returns: `{"root": "#1", "goal": "..."}`.

**Step 2: Start the daemon**

Run `cord daemon` in the background (via the Bash tool):

```bash
cord daemon --budget 2 --log-tools &
```

The daemon watches the DB for new nodes and launches Claude CLI subprocesses for each one. It does **not** create or manage the root — that's you.

**Step 3: Spawn work**

```
Call spawn("Gather raw LCMS data from public repositories")
Call spawn("Identify normalization methods used in literature")
Call spawn("Build feature extraction pipeline", blocked_by=["#2", "#3"])
```

The daemon picks up pending nodes and launches agents for them.

**Step 4: Monitor progress**

```
Call read_tree()
```

Returns the full tree as JSON with statuses, results, and dependencies.

**Step 5: Synthesize and complete**

When children finish, review their results (visible in `read_tree()`) and synthesize:

```
Call complete("Final synthesis: ...")
```

---

## Mode 3: Managed Run (Claude Code as supervisor)

Claude Code describes the problem and cord handles everything autonomously — creating the root agent, spawning children, synthesis — just like `cord run`, but with full MCP visibility and control.

Claude Code is **not** the root agent. It's the supervisor: it launches the tree, monitors progress, and can intervene.

### Setup

Same as Mode 2 — add cord to your project's `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "cord": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/cord",
        "cord-mcp-server"
      ]
    }
  }
}
```

Replace `/path/to/cord` with the absolute path to your cord clone. Restart Claude Code if this is a fresh config.

No daemon startup needed — `run_tree()` handles it automatically.

### Workflow

**Step 1: Launch the tree**

```
Call run_tree("Build a metabolomics analysis pipeline")
```

Or with detailed instructions:

```
Call run_tree(
  goal="Build a metabolomics analysis pipeline",
  prompt="Focus on LCMS data. Use mzML format. Compare at least 3 normalization methods.",
  budget=3.0,
  model="opus"
)
```

Returns: `{"root": "#1", "goal": "...", "daemon_pid": ..., "status": "launched"}`

This creates the DB, root node, and starts a background daemon that launches the root agent as a subprocess. The root agent decomposes the goal, spawns children, and cord manages the full lifecycle including synthesis — all automatically.

**Step 2: Monitor progress**

```
Call read_tree()
```

Returns the full tree with statuses and results for all nodes.

**Step 3: Inspect agent output (optional)**

```
Call read_logs("#2")                                 — see agent #2's stdout (last 100 lines)
Call read_logs("#2", stream="stderr")                — see Claude CLI progress/errors
Call read_logs("#2", tail=0)                         — see full output (all lines)
```

Agent logs are saved to `.cord/agents/{id}.stdout.log` and `.cord/agents/{id}.stderr.log`. They persist after the tree completes.

**Step 4: Intervene (optional)**

```
Call pause("#3")                                    — pause a wayward agent
Call modify("#3", goal="Updated direction")          — redirect paused work
Call resume("#3")                                    — resume after modification
Call stop("#4")                                      — cancel unnecessary work
Call spawn("Additional edge-case analysis")          — inject new top-level work
```

**Step 5: Read results**

When the tree completes, `read_tree()` shows all results including the root's synthesized output.

---

## MCP Tools Reference

These tools are available in Modes 2 and 3 via the cord MCP server.

| Tool | Mode | Description |
|------|------|-------------|
| `run_tree(goal, prompt, budget, model)` | 3 | Launch an autonomous tree. Creates DB, root, starts daemon. |
| `init_tree(goal)` | 2 | Bootstrap a coordination tree. Creates DB, root node, sets agent ID. |
| `spawn(goal, prompt, returns, blocked_by)` | 2, 3 | Create a child task under the root node |
| `fork(goal, prompt, returns, blocked_by)` | 2, 3 | Create a child that inherits sibling context |
| `complete(result)` | 2 | Mark the root as complete with a result |
| `read_tree()` | 2, 3 | Get the full coordination tree as JSON |
| `read_node(node_id)` | 2, 3 | Get a single node's details |
| `read_logs(node_id, stream, tail)` | 2, 3 | Read an agent's stdout/stderr log output |
| `ask(question, options)` | 2, 3 | Request input from a human or parent |
| `stop(node_id)` | 2, 3 | Cancel a node in your subtree |
| `pause(node_id)` | 2, 3 | Pause an active node |
| `resume(node_id)` | 2, 3 | Resume a paused node |
| `modify(node_id, goal, prompt)` | 2, 3 | Update a pending/paused node |

### Guards

If you call `spawn`, `fork`, `complete`, or `ask` without first calling `init_tree()` or `run_tree()` (and without `--agent-id` being set), you'll get:

```json
{"error": "No agent_id set. Call init_tree() or run_tree() first to bootstrap the coordination tree, or ensure --agent-id is passed."}
```

---

## Tool Call Logging

Pass `--log-tools` to `cord run` or `cord daemon` to log every MCP tool call. In Mode 3, pass `--log-tools` in your `.claude/mcp.json` args to enable logging from the MCP server side.

Logs are written to `.cord/tools.log` as JSONL (one JSON object per line):

```json
{"ts":"2026-02-21T14:30:00+00:00","agent":"#1","tool":"spawn","params":{"goal":"Gather data"},"result":"{\"created\": \"#2\", \"goal\": \"Gather data\"}"}
{"ts":"2026-02-21T14:30:01+00:00","agent":"#2","tool":"complete","params":{"result":"Done"},"result":"{\"completed\": \"#2\"}"}
```

Each entry contains:
- `ts` — UTC ISO timestamp
- `agent` — the agent ID that made the call
- `tool` — tool name (`spawn`, `fork`, `complete`, etc.)
- `params` — tool parameters as passed
- `result` — tool return value (truncated to 200 chars)

The log uses Python's `logging.FileHandler` for safe concurrent writes from multiple agent processes.

### Viewing logs

```bash
# Watch live
tail -f .cord/tools.log

# Pretty-print
cat .cord/tools.log | python -m json.tool --json-lines

# Count tool calls by type
cat .cord/tools.log | python -c "
import json, sys, collections
c = collections.Counter(json.loads(l)['tool'] for l in sys.stdin)
for tool, n in c.most_common(): print(f'{tool}: {n}')
"
```

### Agent logs

Each agent's stdout and stderr are saved to `.cord/agents/`:

```
.cord/agents/
    1.stdout.log    # Root agent output
    1.stderr.log    # Root agent Claude CLI progress
    2.stdout.log    # Child #2 output
    2.stderr.log    # Child #2 Claude CLI progress
    ...
```

Logs use append mode — if an agent is relaunched for synthesis, its output appends to the same file.

View via MCP: `read_logs("#2")` or `read_logs("#2", stream="stderr")`.

View from terminal:
```bash
# Watch an agent's output live
tail -f .cord/agents/2.stdout.log

# See all agent outputs
cat .cord/agents/*.stdout.log
```

---

## Project Structure

```
src/cord/
    cli.py                  # cord run | cord daemon [--launch-root]
    db.py                   # SQLite (CordDB class, WAL mode)
    prompts.py              # Prompt assembly for agents
    runtime/
        engine.py           # Main loop, TUI, daemon mode
        dispatcher.py       # Launch claude CLI processes
        process_manager.py  # Track subprocesses
    mcp/
        server.py           # MCP tools (init_tree, run_tree + 10 coordination tools)
```
