"""MCP server for cord — stdio transport, one per agent.

Each claude CLI spawns its own instance via the MCP config.
State is shared through SQLite (WAL mode for concurrent access).
"""

from __future__ import annotations

import datetime
import functools
import json
import logging
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
            "error": "No agent_id set. Call init_tree() first to bootstrap "
            "the coordination tree, or ensure --agent-id is passed."
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
    """Bootstrap a fresh coordination tree. Creates .cord/ dir + SQLite DB,
    creates the root node (#1), and sets this server as the root agent.
    Call this before spawn/fork/complete when using cord from Claude Code."""
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
def read_tree() -> str:
    """Returns the full coordination tree as JSON."""
    db = _get_db()
    tree = db.get_tree()
    if not tree:
        return json.dumps({"error": "No tree found"})
    return json.dumps(_node_to_json(tree), indent=2)


@mcp.tool()
@logged
def read_node(node_id: str) -> str:
    """Returns a single node's details by ID (e.g. '#1')."""
    db = _get_db()
    node = db.get_node(node_id)
    if not node:
        return json.dumps({"error": f"Node {node_id} not found"})
    return json.dumps(_node_to_json(node), indent=2)


@mcp.tool()
@logged
def spawn(goal: str, prompt: str = "", returns: str = "text",
          blocked_by: list[str] | None = None) -> str:
    """Create a spawned child node under your node.
    Use blocked_by to declare dependencies on other node IDs (e.g. ['#2', '#3'])."""
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
    """Create a forked child node (inherits parent context) under your node.
    Use blocked_by to declare dependencies on other node IDs."""
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
    """Mark your node as complete with a result. Call this when your task is done."""
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
    """Cancel a node in your subtree."""
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
            "error": "No agent_id set. Call init_tree() first."
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
    """Pause an active node in your subtree. The runtime will stop its process."""
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
    """Resume a paused node in your subtree. The runtime will relaunch it."""
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
    """Update the goal and/or prompt of a pending or paused node in your subtree."""
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
