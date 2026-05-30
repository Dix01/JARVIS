"""Subprocess execution helper. Async, cross-platform, with timeout."""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    cmd: str
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


async def run_command(
    cmd: str,
    cwd: str | Path | None = None,
    timeout: int = 60,
    shell: str | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a single command line. Uses cmd.exe on Windows, sh elsewhere.

    On Windows, PowerShell can be selected by passing shell='powershell'.
    """
    cwd_str = str(cwd) if cwd else os.getcwd()
    final_env = os.environ.copy()
    if env:
        final_env.update(env)

    if sys.platform == "win32":
        if shell == "powershell":
            argv = ["powershell", "-NoProfile", "-Command", cmd]
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd_str,
                env=final_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=cwd_str,
                env=final_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd_str,
            env=final_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return CommandResult(
            cmd=cmd,
            cwd=cwd_str,
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return CommandResult(
            cmd=cmd,
            cwd=cwd_str,
            returncode=-1,
            stdout="",
            stderr=f"[timeout after {timeout}s]",
            timed_out=True,
        )
