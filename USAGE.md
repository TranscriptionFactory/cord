# Cord Usage Guide

Cord can run in three modes: **standalone** (`cord run`), **MCP integration** (Claude Code as root agent), or **managed run** (`run_tree()` — cord runs autonomously, Claude Code supervises via MCP).

---

## Mode 1: Standalone (`cord run`)

The original mode. Cord creates the root agent, launches everything, and manages the full lifecycle.

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

---

## Mode 2: MCP Integration (Claude Code as root)

In this mode, **you** (via Claude Code) are the root agent `#1`. You call cord's MCP tools directly to spawn children, and `cord daemon` runs in the background to launch and manage child processes.

### Setup (one-time)

Add cord to your project's Claude Code MCP config at `.claude/mcp.json`:

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

No `--agent-id` or `--db-path` needed — when used from Claude Code, the server defaults to `.cord/cord.db` relative to your working directory, and `init_tree()` sets the agent ID.

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

### MCP Tools Reference

| Tool | Description |
|------|-------------|
| `run_tree(goal, prompt, budget, model)` | Launch a full autonomous tree (Mode 3). Creates DB, root, starts daemon. |
| `init_tree(goal)` | Bootstrap a fresh coordination tree (Mode 2). Creates DB, root node, sets agent ID. |
| `spawn(goal, prompt, returns, blocked_by)` | Create a child task under your node |
| `fork(goal, prompt, returns, blocked_by)` | Create a child that inherits sibling context |
| `complete(result)` | Mark your node as complete with a result |
| `read_tree()` | Get the full coordination tree as JSON |
| `read_node(node_id)` | Get a single node's details |
| `ask(question, options)` | Request input from a human or parent |
| `stop(node_id)` | Cancel a node in your subtree |
| `pause(node_id)` | Pause an active node |
| `resume(node_id)` | Resume a paused node |
| `modify(node_id, goal, prompt)` | Update a pending/paused node |

### Guards

If you call `spawn`, `fork`, `complete`, or `ask` without first calling `init_tree()` (or without `--agent-id` being set), you'll get:

```json
{"error": "No agent_id set. Call init_tree() or run_tree() first to bootstrap the coordination tree, or ensure --agent-id is passed."}
```

---

## Mode 3: Managed Run (Claude Code as supervisor)

In this mode, Claude Code describes the problem and cord handles everything autonomously — creating the root agent, spawning children, synthesis — just like `cord run`, but with full MCP visibility and control.

Claude Code is **not** the root agent. It's the supervisor: it launches the tree, monitors progress, and can intervene.

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

Cord creates the DB, root node, and starts a daemon that launches the root agent as a subprocess. The root agent decomposes the goal, spawns children, and cord manages the full lifecycle including synthesis.

**Step 2: Monitor progress**

```
Call read_tree()
```

Returns the full tree with statuses and results for all nodes.

**Step 3: Intervene (optional)**

```
Call pause("#3")                                   — pause a wayward agent
Call modify("#3", goal="Updated direction")         — redirect paused work
Call resume("#3")                                   — resume after modification
Call stop("#4")                                     — cancel unnecessary work
Call spawn("Additional edge-case analysis")         — inject new top-level work
```

**Step 4: Read results**

When the tree completes, `read_tree()` shows all results including the root's synthesized output.

### Mode 3 vs Mode 1 vs Mode 2

| | `cord run` (Mode 1) | MCP Integration (Mode 2) | Managed Run (Mode 3) |
|---|---|---|---|
| **Root agent** | Claude subprocess | Claude Code (you) | Claude subprocess |
| **Supervisor** | None | You | Claude Code |
| **Creates DB** | Yes | `init_tree()` | `run_tree()` |
| **Launches root** | Yes | No (you are root) | Yes (via daemon) |
| **Launches children** | Yes | `cord daemon` | `cord daemon --launch-root` |
| **Synthesizes root** | Yes | You call `complete()` | Yes (automatic) |
| **MCP visibility** | None | Full | Full |
| **Intervention** | None | Full | Full |
| **Use case** | Fire-and-forget | Interactive, hands-on | Supervised autonomy |

---

## Tool Call Logging

Pass `--log-tools` to either `cord run` or `cord daemon` to log every MCP tool call.

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

---

---

## Project Structure

```
src/cord/
    cli.py                  # cord run | cord daemon
    db.py                   # SQLite (CordDB class, WAL mode)
    prompts.py              # Prompt assembly for agents
    runtime/
        engine.py           # Main loop, TUI, daemon mode
        dispatcher.py       # Launch claude CLI processes
        process_manager.py  # Track subprocesses
    mcp/
        server.py           # MCP tools (init_tree, run_tree + 10 coordination tools)
```
