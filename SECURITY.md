# Security Policy

## Scope

JARVIS runs **entirely on your local machine** — it has no servers, no cloud
endpoints, and no telemetry. Security concerns mainly relate to the local attack
surface: the FastAPI backend port, tool permission tiers, and credential handling.

## Supported Versions

| Version | Supported |
|---|---|
| `main` branch | ✅ |
| Older tagged releases | best-effort |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Use [GitHub's private vulnerability reporting](https://github.com/Dix01/JARVIS/security/advisories/new)
to report a vulnerability confidentially. You can expect an acknowledgement
within 72 hours and a fix or mitigation plan within 14 days.

Include:
- A clear description of the vulnerability
- Steps to reproduce or a proof-of-concept
- Potential impact (what an attacker could do)
- Your suggested fix, if you have one

## Known Security Considerations

- **Backend port (`:7341`)** — the FastAPI server listens on `127.0.0.1` by
  default. Do not expose it to the internet or an untrusted network.
- **Tool permission tiers** — SAFE / CAUTION / DANGEROUS tiers gate destructive
  operations. Review `config.yaml` → `permission_mode` before enabling `auto`
  or `bypass` on a sensitive machine.
- **Credentials** — API keys live in `.env` (git-ignored). Never commit `.env`.
  The backend reads keys only at startup; they are never logged or transmitted.
- **Generated media** — files in `data/generated/` are served locally at
  `/api/files/generated/...`. The path-traversal guard in `routes.py` restricts
  access to the allowlisted roots — do not modify this without review.

## Out of Scope

- Vulnerabilities in third-party model weights (FLUX, TRELLIS, Whisper, Piper)
- Issues that require physical access to the machine running JARVIS
- Social-engineering attacks on the user
