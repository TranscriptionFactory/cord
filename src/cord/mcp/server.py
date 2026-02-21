"""MCP server for cord — stdio transport, one per agent.

Each claude CLI spawns its own instance via the MCP config.
State is shared through SQLite (WAL mode for concurrent access).
"""

from __future__ import annotations

import atexit
import datetime
import functools
import json
import logging
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from cord.db import CordDB

# Parse CLI args
agent_id: str | None = None
db_path: str | None = None
log_tools: bool = False

for i, arg in enumerate(sys.argv):
    if arg == "--agent-id" and i + 1 < len(sys.argv):
        agent_id = sys.argv[i + 1]
    if arg == "--db-path" and i + 1 < len(sys.argv):
        db_path = sys.argv[i + 1]
    if arg == "--log-tools":
        log_tools = True

# Default db_path to .cord/cord.db relative to cwd
if not db_path:
    db_path = str(Path.cwd() / ".cord" / "cord.db")

# Tool call logger (JSONL)
_tool_logger: logging.Logger | None = None

if log_tools:
    _tool_logger = logging.getLogger("cord.tools")
    _tool_logger.setLevel(logging.INFO)
    _tool_logger.propagate = False
    log_file = Path(db_path).parent / "tools.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    _handler = logging.FileHandler(str(log_file))
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _tool_logger.addHandler(_handler)


# Daemon subprocess tracking (for run_tree mode)
_daemon_proc: subprocess.Popen | None = None
_daemon_logs: list = []  # open file handles for daemon stdout/stderr


def _cleanup_daemon() -> None:
    """Terminate daemon subprocess and close log handles on exit."""
    if _daemon_proc and _daemon_proc.poll() is None:
        _daemon_proc.terminate()
        try:
            _daemon_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _daemon_proc.kill()
    for f in _daemon_logs:
        if f and not f.closed:
            f.close()


atexit.register(_cleanup_daemon)


def _log_tool_call(tool_name: str, params: dict, result: str) -> None:
    """Log a tool call to .cord/tools.log as JSONL."""
    if _tool_logger is None:
        return
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds"),
        "agent": agent_id or "?",
        "tool": tool_name,
        "params": params,
        "result": result[:200],
    }
    _tool_logger.info(json.dumps(entry, default=str))


def logged(fn):
    """Decorator that logs MCP tool calls when --log-tools is enabled."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        _log_tool_call(fn.__name__, kwargs or {}, result)
        return result
    return wrapper


def _get_db() -> CordDB:
    if db_path:
        return CordDB(db_path)
    raise RuntimeError("No --db-path specified")


def _require_agent_id() -> str | None:
    """Return error JSON if agent_id is not set, else None."""
    if not agent_id:
        return json.dumps({
            "error": "No agent_id set. Call init_tree() or run_tree() first "
            "to bootstrap the coordination tree, or ensure --agent-id is passed."
        })
    return None


def _node_to_json(node: dict) -> dict:
    """Convert a node dict to a clean JSON-serializable dict."""
    d: dict = {
        "id": node["node_id"],
        "type": node["node_type"],
        "goal": node["goal"],
        "status": node["status"],
    }
    if node.get("prompt"):
        d["prompt"] = node["prompt"]
    if node.get("returns"):
        d["returns"] = node["returns"]
    if node.get("result"):
        d["result"] = node["result"]
    if node.get("blocked_by"):
        d["blocked_by"] = node["blocked_by"]
    if node.get("children"):
        d["children"] = [_node_to_json(c) for c in node["children"]]
    return d


mcp = FastMCP("cord")


@mcp.tool()
@logged
def init_tree(goal: str) -> str:
    """Bootstrap a coordination tree with YOU as the root agent (Mode 2).

    Creates .cord/cord.db, inserts root node #1, and sets this session as
    agent #1. After calling this, start `cord daemon` in the background,
    then use spawn/fork to create child tasks, and complete() when done.

    For autonomous operation (Mode 3), use run_tree() instead — it handles
    the daemon automatically and you just monitor with read_tree()."""
    global agent_id

    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    # Wipe existing DB for clean state
    if db_file.exists():
        db_file.unlink()

    db = CordDB(str(db_file))
    root_id = db.create_node(
        node_type="goal",
        goal=goal,
        status="active",
    )
    agent_id = root_id
    return json.dumps({"root": root_id, "goal": goal})


@mcp.tool()
@logged
def run_tree(goal: str, prompt: str = "", budget: float = 2.0,
             model: str = "sonnet") -> str:
    """Launch an autonomous multi-agent tree (Mode 3 — recommended).

    Cord creates a root agent, which decomposes the goal into subtasks,
    spawns child agents, and synthesizes their results — all automatically.
    You are the supervisor: monitor and intervene, but don't need to do
    the work yourself.

    Args:
        goal: What the root agent should accomplish.
        prompt: Optional detailed instructions/context for the root agent.
        budget: Max USD per agent subprocess.
        model: Claude model for agents (sonnet, opus, haiku).

    After calling run_tree:
      1. Poll read_tree() periodically to monitor progress
      2. Intervene if needed: pause/resume/stop/modify any node by ID
      3. Inject additional work with spawn("new task")
      4. When tree completes, read the root's synthesized result"""
    global agent_id, _daemon_proc, _daemon_logs

    # Stop previous daemon and close its log handles
    if _daemon_proc and _daemon_proc.poll() is None:
        _daemon_proc.terminate()
        _daemon_proc.wait()
    for f in _daemon_logs:
        if f and not f.closed:
            f.close()
    _daemon_logs.clear()

    # Create fresh DB
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if db_file.exists():
        db_file.unlink()

    # Create root node (pending — daemon will launch it)
    db = CordDB(str(db_file))
    root_id = db.create_node(
        node_type="goal",
        goal=goal,
        prompt=prompt or None,
        status="pending",
    )
    agent_id = root_id  # Full authority over tree

    # Start daemon with --launch-root
    cord_dir = db_file.parent
    cmd = ["cord", "daemon", "--launch-root",
           "--budget", str(budget), "--model", model]
    if log_tools:
        cmd.append("--log-tools")

    # Resolve project dir (parent of .cord/)
    project_dir = str(cord_dir.parent)

    fout = open(str(cord_dir / "daemon.stdout.log"), "w")
    ferr = open(str(cord_dir / "daemon.stderr.log"), "w")
    _daemon_logs.extend([fout, ferr])

    _daemon_proc = subprocess.Popen(
        cmd, stdout=fout, stderr=ferr, cwd=project_dir,
    )

    return json.dumps({
        "root": root_id,
        "goal": goal,
        "daemon_pid": _daemon_proc.pid,
        "status": "launched",
        "usage": "Monitor with read_tree(). Intervene with "
                 "pause/stop/modify/resume. Inject work with spawn().",
    })


@mcp.tool()
@logged
def read_tree() -> str:
    """Get the full coordination tree as JSON — statuses, results, and
    dependencies for every node. Call periodically after run_tree() or
    init_tree() to monitor progress."""
    db = _get_db()
    tree = db.get_tree()
    if not tree:
        return json.dumps({"error": "No tree found"})
    return json.dumps(_node_to_json(tree), indent=2)


@mcp.tool()
@logged
def read_node(node_id: str) -> str:
    """Get a single node's details by ID (e.g. '#2'). Use instead of
    read_tree() when you only need one node's status or result."""
    db = _get_db()
    node = db.get_node(node_id)
    if not node:
        return json.dumps({"error": f"Node {node_id} not found"})
    return json.dumps(_node_to_json(node), indent=2)


@mcp.tool()
@logged
def read_logs(node_id: str, stream: str = "stdout", tail: int = 100) -> str:
    """Read an agent's log output. Use to inspect what an agent is doing
    or has done — especially useful for debugging failed nodes.

    Args:
        node_id: Node ID (e.g. '#2').
        stream: 'stdout' for agent output, 'stderr' for Claude CLI progress.
        tail: Number of lines to return from the end (default 100, 0 for all).
    """
    if stream not in ("stdout", "stderr"):
        return json.dumps({"error": "stream must be 'stdout' or 'stderr'"})

    cord_dir = Path(db_path).parent
    node_num = node_id.lstrip("#")
    log_path = cord_dir / "agents" / f"{node_num}.{stream}.log"

    if not log_path.exists():
        return json.dumps({
            "error": f"No {stream} log for {node_id}",
            "path": str(log_path),
        })

    text = log_path.read_text()
    if tail > 0:
        lines = text.splitlines()
        if len(lines) > tail:
            text = "\n".join(lines[-tail:])

    return json.dumps({
        "node_id": node_id,
        "stream": stream,
        "lines": len(text.splitlines()),
        "content": text,
    })


@mcp.tool()
@logged
def spawn(goal: str, prompt: str = "", returns: str = "text",
          blocked_by: list[str] | None = None) -> str:
    """Create a child task under the root node. The daemon launches it as
    a Claude subprocess. In Mode 2, use this to decompose your work. In
    Mode 3, use this to inject additional work into a running tree.
    Use blocked_by to declare dependencies (e.g. ['#2', '#3'])."""
    if err := _require_agent_id():
        return err
    db = _get_db()
    new_id = db.create_node(
        node_type="spawn",
        goal=goal,
        parent_id=agent_id,
        prompt=prompt,
        returns=returns,
        blocked_by=blocked_by,
    )
    return json.dumps({"created": new_id, "goal": goal})


@mcp.tool()
@logged
def fork(goal: str, prompt: str = "", returns: str = "text",
         blocked_by: list[str] | None = None) -> str:
    """Create a child that inherits completed sibling results as context.
    Like spawn(), but the child sees what siblings have already produced.
    Use for iterative refinement or tasks that build on prior work."""
    if err := _require_agent_id():
        return err
    db = _get_db()
    new_id = db.create_node(
        node_type="fork",
        goal=goal,
        parent_id=agent_id,
        prompt=prompt,
        returns=returns,
        blocked_by=blocked_by,
    )
    return json.dumps({"created": new_id, "goal": goal})


@mcp.tool()
@logged
def complete(result: str = "") -> str:
    """Mark the root node as complete with a result (Mode 2 only).
    In Mode 3 (run_tree), the root agent completes automatically after
    synthesis — you don't need to call this."""
    if err := _require_agent_id():
        return err
    db = _get_db()
    db.complete_node(agent_id, result)
    return json.dumps({"completed": agent_id})


@mcp.tool()
@logged
def ask(question: str, options: list[str] | None = None,
        default: str | None = None) -> str:
    """Create an ask node to get input from a human or parent agent."""
    if err := _require_agent_id():
        return err
    db = _get_db()
    prompt_text = question
    if options:
        prompt_text += "\nOptions: " + ", ".join(options)
    if default:
        prompt_text += f"\nDefault: {default}"
    new_id = db.create_node(
        node_type="ask",
        goal=question,
        parent_id=agent_id,
        prompt=prompt_text,
        status="pending",
    )
    return json.dumps({"created": new_id, "question": question})


def _is_descendant(db: CordDB, agent_id: str, target_id: str) -> bool:
    """Check if target_id is a descendant of agent_id."""
    node = db.get_node(target_id)
    while node and node["parent_id"]:
        if node["parent_id"] == agent_id:
            return True
        node = db.get_node(node["parent_id"])
    return False


@mcp.tool()
@logged
def stop(node_id: str) -> str:
    """Cancel a node and prevent it from running. Use to cut off
    unnecessary or wayward work (e.g. stop('#3'))."""
    db = _get_db()
    if err := _check_subtree(db, node_id):
        return err
    db.update_status(node_id, "cancelled")
    return json.dumps({"cancelled": node_id})


def _check_subtree(db: CordDB, node_id: str) -> str | None:
    """Return error JSON if node is missing or not in agent's subtree, else None."""
    node = db.get_node(node_id)
    if not node:
        return json.dumps({"error": f"Node {node_id} not found"})
    if not agent_id:
        return json.dumps({
            "error": "No agent_id set. Call init_tree() or run_tree() first."
        })
    if not _is_descendant(db, agent_id, node_id):
        return json.dumps({
            "error": f"Node {node_id} is not in your subtree. "
            "You can only modify your own descendants. "
            "Use ask() to request the parent to do it."
        })
    return None


@mcp.tool()
@logged
def pause(node_id: str) -> str:
    """Pause an active node. Its process stops but can be resumed later.
    Use with modify() to redirect work, then resume()."""
    db = _get_db()
    if err := _check_subtree(db, node_id):
        return err
    node = db.get_node(node_id)
    if node["status"] != "active":
        return json.dumps({"error": f"Node {node_id} is {node['status']}, not active. Only active nodes can be paused."})
    db.update_status(node_id, "paused")
    return json.dumps({"paused": node_id})


@mcp.tool()
@logged
def resume(node_id: str) -> str:
    """Resume a paused node. The daemon will relaunch its process."""
    db = _get_db()
    if err := _check_subtree(db, node_id):
        return err
    node = db.get_node(node_id)
    if node["status"] != "paused":
        return json.dumps({"error": f"Node {node_id} is {node['status']}, not paused. Only paused nodes can be resumed."})
    db.update_status(node_id, "pending")
    return json.dumps({"resumed": node_id})


@mcp.tool()
@logged
def modify(node_id: str, goal: str | None = None, prompt: str | None = None) -> str:
    """Update the goal and/or prompt of a pending or paused node.
    Use after pause() to redirect an agent before resume()."""
    db = _get_db()
    if err := _check_subtree(db, node_id):
        return err
    node = db.get_node(node_id)
    if node["status"] not in ("pending", "paused"):
        return json.dumps({"error": f"Node {node_id} is {node['status']}. Only pending or paused nodes can be modified."})
    if goal is None and prompt is None:
        return json.dumps({"error": "Provide at least one of goal or prompt to modify."})
    db.modify_node(node_id, goal=goal, prompt=prompt)
    updated = db.get_node(node_id)
    return json.dumps({"modified": node_id, "goal": updated["goal"]})


def main():
    """Entry point for cord-mcp-server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
