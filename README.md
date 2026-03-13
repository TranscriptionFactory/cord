# Cord

A coordination protocol for trees of AI coding agents.

One goal in, multiple agents out. They decompose, parallelize, wait on dependencies, and synthesize — all through a shared SQLite database.

## Demo

```
$ cord run "Build a competitive landscape report for fintech" --budget 5.0

cord run

  ● #1 [active] GOAL Build a competitive landscape report for fintech
    ✓ #2 [complete] TASK Identify top fintech competitors
      result: Task complete. JSON array with top 10 fintech companies...
    ✓ #3 [complete] TASK Research fintech industry trends
      result: Task complete. Compiled trends across regulatory, AI...
    ● #4 [active] TASK Deep competitive analysis
      needs: #2, #3
    ○ #5 [pending] TASK Write executive report
      needs: #4

  running: #1, #4
```

The root agent decided to split the work into 4 tasks. #2 and #3 ran in parallel. #4 needs results from both research tasks — their full results are injected into its prompt. #5 waits for #4. When everything completes, #1 relaunches to synthesize the final report.

No workflow was hardcoded. The agent built this tree at runtime.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- An agent CLI that supports MCP servers (default: [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code), see [Custom backends](#custom-backends) for alternatives)

## Install

```bash
git clone https://github.com/kimjune01/cord.git
cd cord
uv sync
```

## Usage

```bash
# Give it a goal
cord run "Analyze the pros and cons of Rust vs Go for CLI tools"

# Or point it at a planning doc
cord run plan.md

# Control budget and model
cord run "goal" --budget 5.0 --model opus

# Use a different agent backend
cord run "goal" --backend my-agent
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--budget` | 2.0 | Max USD per agent subprocess |
| `--model` | sonnet | Model identifier passed to the backend |
| `--backend` | claude | Agent backend (see [Custom backends](#custom-backends)) |

## How it works

```
You                    Engine                 Agents
 │                       │                      │
 │  cord run "goal"      │                      │
 │──────────────────────>│                      │
 │                       │  create root in DB   │
 │                       │  launch root agent   │
 │                       │─────────────────────>│
 │                       │                      │ create("#2", ...)
 │                       │                      │ create("#3", ...)
 │                       │                      │ complete("decomposed")
 │                       │<─────────────────────│
 │                       │                      │
 │                       │  #2 and #3 ready     │
 │                       │  launch both         │
 │                       │─────────────────────>│ (parallel)
 │                       │                      │ complete("result")
 │                       │<─────────────────────│
 │                       │                      │
 │                       │  all children done   │
 │                       │  relaunch #1 for     │
 │                       │  synthesis            │
 │                       │─────────────────────>│
 │                       │                      │ complete("final report")
 │  TUI: all ✓           │<─────────────────────│
 │<──────────────────────│                      │
```

Each agent gets MCP tools to coordinate:

| Tool | What it does |
|------|-------------|
| `create(goal, prompt, returns, needs)` | Create a child task |
| `complete(result)` | Mark yourself done with a result |
| `read_tree()` | See the full coordination tree |
| `read_node(node_id)` | See a single node's details |
| `ask(question, options)` | Request input |
| `stop(node_id)` | Cancel a node |
| `pause(node_id)` | Pause an active node |
| `resume(node_id)` | Resume a paused node |
| `modify(node_id, goal, prompt)` | Update a pending/paused node |

Agents don't know they're in a coordination tree. They see MCP tools and use them as needed. The protocol — dependency tracking, authority scoping, result injection — is enforced by the MCP server.

## Key concepts

**needs** — when creating a child task, list the node IDs whose results it depends on. The engine won't launch the child until all needed nodes complete. Their full results are injected into the child's prompt. This is the single context-engineering primitive: you choose which results flow to each child.

**Context rot** — if a child would need results from many nodes, create an intermediate task to synthesize them first. Each level of tree depth is a natural compression boundary. Prefer deeper trees over wide fan-ins.

**Two-phase execution** — an agent decomposes (creates children, calls `complete`). The engine waits for children. When all children finish, the engine relaunches the parent with a synthesis prompt that includes children's results.

**Authority** — agents can only create children under themselves and stop nodes in their own subtree. They can't touch siblings or ancestors.

## Project structure

```
src/cord/
    cli.py                  # cord run "goal"
    db.py                   # SQLite (CordDB class, WAL mode)
    prompts.py              # Prompt assembly for agents
    runtime/
        backends.py         # AgentBackend protocol + built-in backends
        engine.py           # Main loop, TUI
        dispatcher.py       # Launch agent processes
        process_manager.py  # Track subprocesses
    mcp/
        server.py           # MCP tools (one server per agent)
```

~1020 lines of source. SQLite is the only dependency beyond the MCP library.

## Tests

```bash
uv run pytest tests/ -v   # 49 tests
```

## Experiments

[`experiments/behavior_compare.py`](experiments/behavior_compare.py) runs 8 behavioral tests against both Opus and Sonnet via Claude Code CLI, comparing how each model uses the Cord MCP tools. The earlier behavior tests (see [BEHAVIOR.md](BEHAVIOR.md)) were run against the v0.3 API which used separate `spawn`/`fork` primitives — these have since been unified into `create` with explicit `needs`.

The `pause`, `resume`, and `modify` tools were added because Claude independently tried to call them before they existed ([BEHAVIOR.md](BEHAVIOR.md) test 13). We built what the model already expected.

## Costs

Each agent subprocess has its own Claude API budget (set via `--budget`). A simple 2-node task costs ~$0.10. The demo fintech report (4 agents + synthesis) costs ~$2-4. Costs scale with the number of agents and their complexity.

## Custom backends

Cord is agent-agnostic. The `AgentBackend` protocol in `src/cord/runtime/backends.py` defines how agent subprocesses are launched. Any CLI agent that supports MCP servers can be used.

### The protocol

A backend is a class with two things:

```python
from pathlib import Path
from cord.runtime.backends import AgentBackend, BACKENDS

class MyAgentBackend:
    name: str = "my-agent"

    def build_command(
        self,
        prompt: str,
        *,
        model: str,
        mcp_config_path: Path,
        max_budget_usd: float,
        allowed_tools: list[str] | None = None,
    ) -> list[str]:
        """Return the argv list to launch one agent subprocess."""
        return [
            "my-agent-cli",
            "--prompt", prompt,
            "--model", model,
            "--mcp-config", str(mcp_config_path),
            "--budget", str(max_budget_usd),
        ]
```

- `name` — identifier used with `--backend` on the CLI and `backend` in `run_tree()`
- `build_command()` — returns the full command list. Cord handles process lifecycle, stdio redirection, and working directory. Your backend just builds the argv.

The `mcp_config_path` points to a JSON file cord generates with its MCP server config. Your agent CLI must load this so the agent gets access to cord's coordination tools (`create`, `complete`, `read_tree`, etc.). If your agent doesn't support a `--mcp-config` flag, your backend can convert the JSON into whatever format the agent expects (see `CodexBackend` for an example that writes a `.codex/config.toml`).

### Registering a backend

Add your class to the `BACKENDS` dict in `backends.py`:

```python
BACKENDS: dict[str, type[AgentBackend]] = {
    "claude": ClaudeCodeBackend,
    "my-agent": MyAgentBackend,
}
```

Then use it:

```bash
cord run "goal" --backend my-agent --model gpt-4o
```

Or via MCP:

```python
run_tree("goal", backend="my-agent", model="gpt-4o")
```

### Requirements for a compatible agent CLI

Your agent CLI must:

1. **Accept a prompt** — run non-interactively with a provided prompt
2. **Load MCP config** — read the JSON file at `mcp_config_path` and connect to cord's stdio MCP server
3. **Run to completion** — exit with code 0 on success, non-zero on failure
4. **Output result to stdout** — if the agent doesn't call `complete()` via MCP, cord uses stdout as the result

The `--model` and `--budget` flags are passed through as-is — your backend interprets them however it wants (or ignores them).

### Built-in backends

| Name | CLI | Description |
|------|-----|-------------|
| `claude` | `claude` | Claude Code CLI (default) |
| `codex` | `codex exec` | OpenAI Codex CLI |

**Codex notes:** Codex doesn't support a per-invocation `--mcp-config` flag. The `codex` backend automatically converts cord's MCP config JSON into a project-scoped `.codex/config.toml` before each launch. Codex also has no budget flag, so `--budget` is ignored. Usage:

```bash
cord run "goal" --backend codex --model o4-mini
```

## Limitations

- Single machine only. Agents are local processes.
- No web UI — terminal TUI only.
- No mid-execution message injection (pause/modify/resume requires relaunch).
- Each agent gets its own MCP server process (~200ms startup overhead).
- Requires an agent CLI that supports MCP servers (see [Custom backends](#custom-backends)).

## Alternative implementations

This repo is one implementation of the Cord protocol. The protocol itself — four primitives, dependency resolution, authority scoping, two-phase lifecycle — is independent of the backing store, transport, and agent runtime. You could implement Cord with Redis pub/sub, Postgres for multi-machine coordination, HTTP/SSE instead of stdio MCP, or non-Claude agents. See [RFC.md](RFC.md) for the full protocol specification.

## License

MIT
