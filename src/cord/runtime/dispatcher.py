"""Launch agent processes for cord nodes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cord.runtime.backends import AgentBackend, ClaudeCodeBackend


# Cord's own project root (where pyproject.toml lives), for uv run --project
_CORD_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

MCP_TOOLS = [
    "mcp__cord__init_tree",
    "mcp__cord__read_tree",
    "mcp__cord__read_node",
    "mcp__cord__create",
    "mcp__cord__ask",
    "mcp__cord__stop",
    "mcp__cord__complete",
    "mcp__cord__pause",
    "mcp__cord__resume",
    "mcp__cord__modify",
]


def generate_mcp_config(
    db_path: Path,
    agent_id: str,
    log_tools: bool = False,
) -> dict:
    """Generate MCP config that spawns a stdio server for this agent."""
    args = [
        "run",
        "--project", str(_CORD_PROJECT_ROOT),
        "cord-mcp-server",
        "--db-path", str(db_path.resolve()),
        "--agent-id", agent_id,
    ]
    if log_tools:
        args.append("--log-tools")

    return {
        "mcpServers": {
            "cord": {
                "command": "uv",
                "args": args,
            }
        }
    }


def launch_agent(
    db_path: Path,
    node_id: str,
    prompt: str,
    work_dir: Path | None = None,
    max_budget_usd: float = 2.0,
    model: str = "sonnet",
    log_tools: bool = False,
    log_dir: Path | None = None,
    allowed_tools: list[str] | None = None,
    backend: AgentBackend | None = None,
) -> subprocess.Popen[str]:
    """Launch an agent process for a node.

    Args:
        log_dir: If set, write agent stdout/stderr to log files in this
            directory (e.g. .cord/agents/). Uses append mode so synthesis
            reruns append to the same file.
        allowed_tools: If set, restrict agent to these tools via --allowedTools.
            If None (default), agent can use all available tools (built-in +
            MCP servers from global config and cord's own server).
        backend: Agent backend to use. Defaults to ClaudeCodeBackend.
    """
    if backend is None:
        backend = ClaudeCodeBackend()

    mcp_config = generate_mcp_config(db_path, node_id, log_tools=log_tools)

    config_dir = db_path.parent / ".cord"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"mcp-{node_id.lstrip('#')}.json"
    config_path.write_text(json.dumps(mcp_config, indent=2))

    cmd = backend.build_command(
        prompt,
        model=model,
        mcp_config_path=config_path,
        max_budget_usd=max_budget_usd,
        allowed_tools=allowed_tools,
    )

    cwd = str(work_dir) if work_dir else str(db_path.parent)

    # Log agent output to files when log_dir is set
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        node_num = node_id.lstrip("#")
        fout = open(log_dir / f"{node_num}.stdout.log", "a")
        ferr = open(log_dir / f"{node_num}.stderr.log", "a")
        process = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=fout, stderr=ferr, text=True, cwd=cwd,
        )
        # Safe to close — child process has its own file descriptors
        fout.close()
        ferr.close()
    else:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
        )

    return process
