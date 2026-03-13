"""Agent backends — how cord launches child agent processes.

Each backend knows how to build a CLI command for a specific agent runtime.
The default is Claude Code, but any CLI agent that supports MCP can be used.
"""

from __future__ import annotations

import json
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


class CodexBackend:
    """Backend for OpenAI Codex CLI.

    Codex doesn't support a per-invocation --mcp-config flag. Instead, MCP
    servers are configured via a project-scoped .codex/config.toml file.
    This backend reads cord's MCP config JSON and writes the equivalent
    TOML into .codex/config.toml next to the working directory before
    building the command.
    """

    name: str = "codex"

    def build_command(
        self,
        prompt: str,
        *,
        model: str,
        mcp_config_path: Path,
        max_budget_usd: float,
        allowed_tools: list[str] | None = None,
    ) -> list[str]:
        # Convert cord's MCP JSON config into Codex's .codex/config.toml
        self._write_codex_mcp_config(mcp_config_path)

        cmd = [
            "codex", "exec",
            "--model", model,
            "--dangerously-bypass-approvals-and-sandbox",
            prompt,
        ]
        return cmd

    @staticmethod
    def _write_codex_mcp_config(mcp_config_path: Path) -> None:
        """Read cord's MCP JSON and write a .codex/config.toml for Codex."""
        mcp_json = json.loads(mcp_config_path.read_text())
        servers = mcp_json.get("mcpServers", {})

        lines: list[str] = []
        for server_name, server_cfg in servers.items():
            command = server_cfg.get("command", "")
            args = server_cfg.get("args", [])
            env = server_cfg.get("env", {})

            lines.append(f"[mcp_servers.{server_name}]")
            lines.append(f'command = "{command}"')
            if args:
                # Format as TOML array of strings
                formatted = ", ".join(f'"{a}"' for a in args)
                lines.append(f"args = [{formatted}]")
            if env:
                lines.append(f"[mcp_servers.{server_name}.env]")
                for k, v in env.items():
                    lines.append(f'{k} = "{v}"')
            lines.append("")

        # Write to .codex/config.toml next to the MCP config's parent
        # (.cord/ dir lives in the project root, so go up one level)
        project_dir = mcp_config_path.parent.parent
        codex_dir = project_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text("\n".join(lines) + "\n")


# Registry of built-in backends by name
BACKENDS: dict[str, type[AgentBackend]] = {
    "claude": ClaudeCodeBackend,
    "codex": CodexBackend,
}


def get_backend(name: str = "claude", **kwargs) -> AgentBackend:
    """Look up a backend by name and instantiate it."""
    cls = BACKENDS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown backend {name!r}. Available: {', '.join(BACKENDS)}"
        )
    return cls(**kwargs)
