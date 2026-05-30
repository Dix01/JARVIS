"""OPTIONAL: Email scaffold (SMTP sender).

Reads SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS from .env.
Sending is always DANGEROUS — explicit confirmation required.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from ..core.permissions import Permission
from .base import PluginInfo, tool


def register(registry):
    @tool(
        name="send_email",
        description="Send an email via configured SMTP. DANGEROUS — explicit confirmation each time.",
        permission=Permission.DANGEROUS,
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        preview=lambda a: f"EMAIL to={a.get('to')}, subj={a.get('subject','')[:60]}",
    )
    def send_email(to: str, subject: str, body: str) -> str:
        host = os.environ.get("SMTP_HOST", "")
        port = int(os.environ.get("SMTP_PORT", "0") or 0)
        user = os.environ.get("SMTP_USER", "")
        pw = os.environ.get("SMTP_PASS", "")
        if not (host and port and user and pw):
            return "SMTP_* env vars missing"

        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(user, pw)
                s.send_message(msg)
        except Exception as e:  # noqa: BLE001
            return f"send failed: {e}"
        return f"sent to {to}"

    registry.add_pending("email_optional")
    registry.register_plugin(PluginInfo(
        name="email_optional",
        description="OPTIONAL SMTP email sending.",
        permissions_needed=[Permission.DANGEROUS],
    ))
