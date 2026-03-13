"""CLI for cord: cord run "goal" [options] | cord daemon [options]."""

from __future__ import annotations

import sys
from pathlib import Path

from cord.runtime.backends import get_backend
from cord.runtime.engine import Engine


def _parse_flag(args: list[str], flag: str, default: str | None = None) -> str | None:
    """Extract a --flag value from args list."""
    if flag in args:
        idx = args.index(flag)
        if idx + 1 < len(args):
            return args[idx + 1]
    return default


def main() -> None:
    """CLI entry point: cord run | cord daemon."""
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print("Usage:")
        print('  cord run "goal description" [--budget <usd>] [--model <model>] [--backend <name>] [--log-tools]')
        print('  cord run plan.md [--budget <usd>] [--model <model>] [--backend <name>] [--log-tools]')
        print('  cord daemon [--budget <usd>] [--model <model>] [--backend <name>] [--log-tools] [--launch-root]')
        sys.exit(0)

    command = args[0]
    budget = float(_parse_flag(args, "--budget", "2.0"))
    model = _parse_flag(args, "--model", "sonnet")
    backend_name = _parse_flag(args, "--backend", "claude")
    backend = get_backend(backend_name)
    log_tools_flag = "--log-tools" in args

    if command == "run":
        if len(args) < 2:
            print('Usage: cord run "goal description" [--budget <usd>] [--model <model>] [--backend <name>] [--log-tools]', file=sys.stderr)
            sys.exit(1)

        goal_arg = args[1]
        goal_path = Path(goal_arg)
        if goal_path.exists() and goal_path.is_file():
            goal = goal_path.read_text().strip()
        else:
            goal = goal_arg

        engine = Engine(goal, max_budget_usd=budget, model=model,
                        backend=backend, log_tools=log_tools_flag)
        engine.run()

    elif command == "daemon":
        launch_root = "--launch-root" in args
        engine = Engine(
            goal="(managed run)" if launch_root
                 else "(daemon — root managed externally)",
            max_budget_usd=budget,
            model=model,
            backend=backend,
            fresh_db=False,
            skip_root_synthesis=not launch_root,
            log_tools=log_tools_flag,
        )
        engine.run_daemon(launch_root=launch_root)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Commands: run, daemon", file=sys.stderr)
        sys.exit(1)
