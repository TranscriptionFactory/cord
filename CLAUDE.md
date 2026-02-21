# Cord — Multi-Agent Coordination

Cord coordinates trees of Claude Code agents through a shared SQLite database.

## Using Cord's MCP Tools

When cord is configured as an MCP server (via `.claude/mcp.json`), use **Mode 3 (Managed Run)** by default — it's the simplest path:

### Recommended workflow

1. **Launch**: Call `run_tree(goal, prompt)` with the user's problem description
2. **Poll**: Call `read_tree()` every 30-60 seconds to monitor progress
3. **Intervene** (if needed):
   - `pause(node_id)` / `resume(node_id)` — pause/resume a specific agent
   - `modify(node_id, goal=..., prompt=...)` — redirect a paused/pending agent
   - `stop(node_id)` — cancel a node entirely
   - `spawn(goal)` — inject additional work into the tree
4. **Report**: When all nodes show `complete`, relay the root's result to the user

### When to use Mode 2 instead

Use `init_tree(goal)` + manual `spawn()` calls + `cord daemon` when the user wants to manually decompose the problem and control each child task themselves. In Mode 2, the user (via you) IS the root agent and must call `complete()` to finish.

### Tips

- Node IDs look like `#1`, `#2`, etc.
- `spawn()` creates independent children; `fork()` creates children that inherit sibling results
- `blocked_by=["#2", "#3"]` makes a node wait for dependencies before launching
- The tree synthesizes automatically — when all children finish, the parent is relaunched to combine their results

## Developing Cord

See `USAGE.md` for full documentation of all three modes. See `README.md` for architecture and testing.

### Project structure

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
