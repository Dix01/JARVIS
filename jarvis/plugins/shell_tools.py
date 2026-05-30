"""Shell command execution.

run_shell      -- generic command via cmd.exe (Windows) or sh (POSIX)
run_powershell -- PowerShell variant
which          -- locate an executable on PATH
env_var        -- read an environment variable (SAFE)
"""
from __future__ import annotations

import os
import shutil

from ..core.permissions import Permission
from ..utils.shell import run_command
from .base import PluginInfo, tool


def register(registry):
    cfg = registry.cfg
    memory = registry.services.get("memory")

    @tool(
        name="run_shell",
        description="Run a shell command. Returns stdout, stderr, return code. cwd is optional, defaults to project root.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command line."},
                "cwd": {"type": "string", "description": "Working directory.", "default": ""},
                "timeout": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
        preview=lambda a: f"shell> {a.get('command','')}",
    )
    async def run_shell(command: str, cwd: str = "", timeout: int = 60) -> str:
        target_cwd = cwd or str(cfg.project_root)
        res = await run_command(command, cwd=target_cwd, timeout=timeout)
        if memory is not None:
            memory.bump_command(command)
        return _format_result(res)

    @tool(
        name="run_powershell",
        description="Run a PowerShell command on Windows.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "default": ""},
                "timeout": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
        preview=lambda a: f"PS> {a.get('command','')}",
    )
    async def run_powershell(command: str, cwd: str = "", timeout: int = 60) -> str:
        target_cwd = cwd or str(cfg.project_root)
        res = await run_command(command, cwd=target_cwd, timeout=timeout, shell="powershell")
        if memory is not None:
            memory.bump_command(f"powershell: {command}")
        return _format_result(res)

    @tool(
        name="which",
        description="Locate an executable on PATH. Returns its absolute path or empty string.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    def which(name: str) -> str:
        return shutil.which(name) or ""

    @tool(
        name="env_var",
        description="Read an environment variable by name.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    def env_var(name: str) -> str:
        return os.environ.get(name, "")

    registry.add_pending("shell_tools")
    registry.register_plugin(PluginInfo(
        name="shell_tools",
        description="Shell + PowerShell execution, PATH lookup, env vars.",
        permissions_needed=[Permission.CAUTION],
    ))


def _format_result(res) -> str:
    lines = [f"$ {res.cmd}", f"cwd: {res.cwd}", f"returncode: {res.returncode}"]
    if res.timed_out:
        lines.append("TIMED OUT")
    if res.stdout:
        lines.append("--- stdout ---")
        lines.append(_clip(res.stdout, 4000))
    if res.stderr:
        lines.append("--- stderr ---")
        lines.append(_clip(res.stderr, 4000))
    return "\n".join(lines)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n... [clipped, {len(s)} chars total]"
