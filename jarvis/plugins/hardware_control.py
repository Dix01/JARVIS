"""Hardware control tools: display brightness, master volume, and installed game discovery."""
from __future__ import annotations

import os
import platform
import re
from typing import Any

from ..core.permissions import Permission
from .base import PluginInfo, tool


def register(registry):
    @tool(
        name="adjust_brightness",
        description="Get or adjust laptop screen brightness (increase, decrease, set to percentage).",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform: 'increase', 'decrease', 'set', or 'get'",
                    "default": "get",
                },
                "value": {
                    "type": "integer",
                    "description": "Target brightness percentage (0-100) or step amount",
                },
            },
        },
    )
    def adjust_brightness(action: str = "get", value: int | None = None) -> str:
        try:
            import screen_brightness_control as sbc
            curr = sbc.get_brightness()
            curr_val = curr[0] if isinstance(curr, list) and curr else 50

            act = (action or "get").lower().strip()
            if act == "set" and value is not None:
                new_val = max(0, min(100, int(value)))
                sbc.set_brightness(new_val)
                return f"Brightness set to {new_val}%."
            elif any(w in act for w in ["inc", "up", "more", "raise", "+"]):
                step = int(value) if value else 15
                new_val = min(100, curr_val + step)
                sbc.set_brightness(new_val)
                return f"Brightness increased to {new_val}%."
            elif any(w in act for w in ["dec", "down", "lower", "less", "-"]):
                step = int(value) if value else 15
                new_val = max(0, curr_val - step)
                sbc.set_brightness(new_val)
                return f"Brightness decreased to {new_val}%."
            else:
                return f"Current screen brightness is {curr_val}%."
        except Exception as e:
            return f"Failed to adjust screen brightness: {e}"

    @tool(
        name="adjust_volume",
        description="Control Windows master audio volume: 'increase', 'decrease', or 'mute'.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Volume action: 'increase', 'decrease', or 'mute'",
                    "default": "increase",
                }
            },
        },
    )
    def adjust_volume(action: str = "increase") -> str:
        if platform.system() != "Windows":
            return "Volume control via user32 keystroke is Windows-only."
        try:
            import ctypes
            act = (action or "increase").lower().strip()
            if any(w in act for w in ["up", "inc", "more", "raise", "loud"]):
                for _ in range(5):
                    ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
                return "Master volume increased."
            elif any(w in act for w in ["down", "dec", "less", "quiet", "lower"]):
                for _ in range(5):
                    ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
                return "Master volume decreased."
            elif "mute" in act or "unmute" in act:
                ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
                return "Master volume mute toggled."
            return "Volume action executed."
        except Exception as e:
            return f"Failed to adjust volume: {e}"

    @tool(
        name="get_installed_games",
        description="Detect installed PC games (inspects Steam libraries and Windows gaming entries).",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def get_installed_games() -> str:
        games: set[str] = set()

        # 1. Steam Common folder
        steam_dirs = [
            r"C:\Program Files (x86)\Steam\steamapps\common",
            r"C:\Program Files\Steam\steamapps\common",
            r"D:\SteamLibrary\steamapps\common",
            r"E:\SteamLibrary\steamapps\common",
        ]
        ignored_steam = {"steamworks shared", "steam controller configs"}
        for s_dir in steam_dirs:
            if os.path.exists(s_dir):
                for f in os.listdir(s_dir):
                    if os.path.isdir(os.path.join(s_dir, f)) and f.lower() not in ignored_steam:
                        games.add(f)

        # 2. Windows Registry Gaming / App entries
        try:
            import winreg
            keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            ]
            for root, sub in keys:
                try:
                    with winreg.OpenKey(root, sub) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            try:
                                subname = winreg.EnumKey(k, i)
                                with winreg.OpenKey(k, subname) as appkey:
                                    name, _ = winreg.QueryValueEx(appkey, "DisplayName")
                                    # Filter out common redistributables, drivers, and system updates
                                    lower_name = name.lower()
                                    if any(ex in lower_name for ex in [
                                        "microsoft visual", "redistributable", "update", "driver",
                                        "runtime", "windows software", "security update", "nvidia"
                                    ]):
                                        continue
                                    # If it has a SteamAppId or looks like a game
                                    is_game = False
                                    try:
                                        winreg.QueryValueEx(appkey, "SteamAppId")
                                        is_game = True
                                    except OSError:
                                        pass
                                    if not is_game:
                                        try:
                                            url, _ = winreg.QueryValueEx(appkey, "HelpLink")
                                            if "steampowered" in url.lower() or "epicgames" in url.lower():
                                                is_game = True
                                        except OSError:
                                            pass
                                    if is_game:
                                        clean_name = re.sub(r'\s*[\(\[].*?[\)\]]', '', name).strip()
                                        games.add(clean_name)
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

        if not games:
            return "No installed games detected in standard library locations."
        return f"Detected installed games ({len(games)} found):\n- " + "\n- ".join(sorted(games))

    registry.add_pending("hardware_control")
    registry.register_plugin(
        PluginInfo(
            name="hardware_control",
            description="Controls display brightness, master volume, and discovers installed games.",
            permissions_needed=[Permission.SAFE],
        )
    )
