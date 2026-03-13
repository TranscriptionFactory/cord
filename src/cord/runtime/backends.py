"""Agent backends — how cord launches child agent processes.

Each backend knows how to build a CLI command for a specific agent runtime.
The default is Claude Code, but any CLI agent that supports MCP can be used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentBackend(Protocol):
    """Interface for building agent CLI commands."""

    name: str

    def build_command(
        self,
        prompt: str,
        *,
        model: str,
        mcp_config_path: Path,
        max_budget_usd: float,
        allowed_tools: list[str] | None = None,
    ) -> list[str]:
        """Return the full argv list to launch an agent subprocess."""
        ...


class ClaudeCodeBackend:
    """Default backend: launches agents via the `claude` CLI."""

    name: str = "claude"

    def build_command(
        self,
        prompt: str,
        *,
        model: str,
        mcp_config_path: Path,
        max_budget_usd: float,
        allowed_tools: list[str] | None = None,
    ) -> list[str]:
        cmd = [
            "claude",
            "-p", prompt,
            "--model", model,
            "--mcp-config", str(mcp_config_path),
            "--dangerously-skip-permissions",
            "--max-budget-usd", str(max_budget_usd),
        ]
        if allowed_tools is not None:
            cmd.extend(["--allowedTools", " ".join(allowed_tools)])
        return cmd


# Registry of built-in backends by name
BACKENDS: dict[str, type[AgentBackend]] = {
    "claude": ClaudeCodeBackend,
}


def get_backend(name: str = "claude", **kwargs) -> AgentBackend:
    """Look up a backend by name and instantiate it."""
    cls = BACKENDS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown backend {name!r}. Available: {', '.join(BACKENDS)}"
        )
    return cls(**kwargs)
