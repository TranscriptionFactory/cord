"""Track and manage agent subprocess lifecycle."""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProcessInfo:
    node_id: str
    process: subprocess.Popen[str]
    stdout_path: Path | None = None


class ProcessManager:
    """Manages agent subprocesses for active nodes."""

    def __init__(self) -> None:
        self._processes: dict[str, ProcessInfo] = {}

    def register(
        self,
        node_id: str,
        process: subprocess.Popen[str],
        stdout_path: Path | None = None,
    ) -> None:
        """Register a subprocess for a node.

        Args:
            stdout_path: Path to the agent's stdout log file. When set,
                poll_completions reads stdout from this file instead of PIPE.
        """
        self._processes[node_id] = ProcessInfo(
            node_id=node_id, process=process, stdout_path=stdout_path,
        )

    def poll_completions(self) -> list[tuple[str, int, str]]:
        """Poll all registered processes for completions.

        Returns list of (node_id, return_code, stdout) for completed processes.
        """
        completed = []
        for node_id, info in list(self._processes.items()):
            rc = info.process.poll()
            if rc is not None:
                stdout = ""
                if info.stdout_path and info.stdout_path.exists():
                    stdout = info.stdout_path.read_text()
                elif info.process.stdout:
                    stdout = info.process.stdout.read() or ""
                completed.append((node_id, rc, stdout))
                del self._processes[node_id]
        return completed

    def cancel(self, node_id: str) -> bool:
        """Send SIGTERM to a node's process. Returns True if signal was sent."""
        info = self._processes.get(node_id)
        if info is None:
            return False
        try:
            os.kill(info.process.pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False

    def cancel_all(self) -> None:
        """Cancel all running processes."""
        for node_id in list(self._processes.keys()):
            self.cancel(node_id)

    @property
    def active_count(self) -> int:
        return len(self._processes)

    @property
    def active_node_ids(self) -> set[str]:
        return set(self._processes.keys())
