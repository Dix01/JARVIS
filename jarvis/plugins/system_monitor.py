"""Live system stats: CPU, RAM, disk, GPU, network, battery, processes."""
from __future__ import annotations

import platform
import shutil

import psutil

from ..core.permissions import Permission
from .base import PluginInfo, tool


def register(registry):
    @tool(
        name="system_status",
        description="Snapshot of CPU/RAM/disk/uptime/OS.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def system_status() -> str:
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        root = "C:\\" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(root)
        uname = platform.uname()
        lines = [
            f"OS: {uname.system} {uname.release} ({uname.version})",
            f"Host: {uname.node}",
            f"CPU usage: {cpu:.1f}%  | cores: {psutil.cpu_count(logical=True)}",
            f"RAM: {mem.percent:.1f}% used ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)",
            f"Disk: {disk.percent:.1f}% used ({disk.used/1e9:.1f}/{disk.total/1e9:.1f} GB)",
        ]
        try:
            la = psutil.getloadavg()
            lines.append(f"Load avg: {la[0]:.2f} {la[1]:.2f} {la[2]:.2f}")
        except (AttributeError, OSError):
            pass
        return "\n".join(lines)

    @tool(
        name="list_processes",
        description="List top processes by CPU usage.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 15}},
        },
    )
    def list_processes(limit: int = 15) -> str:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: (x.get("cpu_percent") or 0), reverse=True)
        lines = [f"{'PID':>7}  {'CPU%':>6}  {'MEM%':>6}  NAME"]
        for p in procs[:limit]:
            lines.append(
                f"{p.get('pid'):>7}  {(p.get('cpu_percent') or 0):>5.1f}  "
                f"{(p.get('memory_percent') or 0):>5.1f}  {p.get('name','')}"
            )
        return "\n".join(lines)

    @tool(
        name="network_info",
        description="Network interfaces and current send/recv counters.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def network_info() -> str:
        io = psutil.net_io_counters(pernic=True)
        addrs = psutil.net_if_addrs()
        lines: list[str] = []
        for name, ad in addrs.items():
            ips = ", ".join(a.address for a in ad if a.family.name in ("AF_INET", "AF_INET6"))
            stats = io.get(name)
            tx = f" tx={stats.bytes_sent/1e6:.1f}MB rx={stats.bytes_recv/1e6:.1f}MB" if stats else ""
            lines.append(f"{name}: {ips}{tx}")
        return "\n".join(lines) or "(no interfaces)"

    @tool(
        name="battery",
        description="Battery percent + charging state. Reports 'no battery' on desktops.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def battery() -> str:
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if b is None:
            return "no battery detected"
        plugged = "charging" if b.power_plugged else "on battery"
        secs = "" if b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else f", {b.secsleft//60} min left"
        return f"{b.percent:.0f}% ({plugged}{secs})"

    @tool(
        name="gpu_info",
        description="Detected GPUs. NVIDIA stats if nvidia-smi is on PATH.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    async def gpu_info() -> str:
        if not shutil.which("nvidia-smi"):
            return "no nvidia-smi on PATH (GPU stats unavailable)"
        from ..utils.shell import run_command
        res = await run_command(
            "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu "
            "--format=csv,noheader,nounits",
            timeout=10,
        )
        return res.stdout.strip() or res.stderr.strip()

    @tool(
        name="disk_usage",
        description="Disk usage for a path (default: project root drive).",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "default": ""}},
        },
    )
    def disk_usage(path: str = "") -> str:
        target = path or "C:\\"
        du = psutil.disk_usage(target)
        return f"{target}: {du.percent:.1f}% used  {du.used/1e9:.1f}/{du.total/1e9:.1f} GB"

    @tool(
        name="kill_process",
        description="Terminate a process by PID. DANGEROUS.",
        permission=Permission.DANGEROUS,
        parameters={
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
        },
        preview=lambda a: f"KILL pid={a.get('pid')}",
    )
    def kill_process(pid: int) -> str:
        try:
            p = psutil.Process(pid)
            name = p.name()
            p.terminate()
            return f"terminated {name} (pid={pid})"
        except psutil.NoSuchProcess:
            return f"no such process: {pid}"
        except psutil.AccessDenied:
            return f"access denied terminating pid {pid}"

    registry.add_pending("system_monitor")
    registry.register_plugin(PluginInfo(
        name="system_monitor",
        description="CPU/RAM/disk/network/battery/processes/GPU monitoring.",
        permissions_needed=[Permission.SAFE, Permission.DANGEROUS],
    ))
