"""OPTIONAL: Smart-home integration scaffold (Home Assistant REST API).

Set HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in .env, enable the plugin,
and JARVIS can query/control entities through your local HA instance.
"""
from __future__ import annotations

import os

import httpx

from ..core.permissions import Permission
from .base import PluginInfo, tool


def register(registry):
    @tool(
        name="ha_states",
        description="List all Home Assistant entity states (or filter by domain like 'light').",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"domain": {"type": "string", "default": ""}},
        },
    )
    async def ha_states(domain: str = "") -> str:
        url, headers = _ha_auth()
        if not url:
            return "HOME_ASSISTANT_URL / HOME_ASSISTANT_TOKEN missing"
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url + "/api/states", headers=headers)
            r.raise_for_status()
        data = r.json()
        if domain:
            data = [e for e in data if e["entity_id"].startswith(domain + ".")]
        return "\n".join(f"{e['entity_id']}: {e['state']}" for e in data[:50])

    @tool(
        name="ha_call_service",
        description="Call a Home Assistant service, e.g. domain='light' service='turn_on' entity_id='light.kitchen'.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "service": {"type": "string"},
                "entity_id": {"type": "string"},
                "data": {"type": "object", "default": {}},
            },
            "required": ["domain", "service", "entity_id"],
        },
        preview=lambda a: f"HA {a.get('domain')}.{a.get('service')} -> {a.get('entity_id')}",
    )
    async def ha_call_service(domain: str, service: str, entity_id: str, data: dict | None = None) -> str:
        url, headers = _ha_auth()
        if not url:
            return "HOME_ASSISTANT_URL / HOME_ASSISTANT_TOKEN missing"
        body = {"entity_id": entity_id, **(data or {})}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{url}/api/services/{domain}/{service}", headers=headers, json=body)
            r.raise_for_status()
        return f"called {domain}.{service} on {entity_id}"

    registry.add_pending("smart_home_optional")
    registry.register_plugin(PluginInfo(
        name="smart_home_optional",
        description="OPTIONAL Home Assistant control.",
        permissions_needed=[Permission.CAUTION],
    ))


def _ha_auth() -> tuple[str, dict[str, str]]:
    url = os.environ.get("HOME_ASSISTANT_URL", "").rstrip("/")
    token = os.environ.get("HOME_ASSISTANT_TOKEN", "")
    if not (url and token):
        return "", {}
    return url, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
