"""Outbound safety guardrails and dry-run preview mechanisms."""

import sys
from typing import Any, Dict, Optional


def render_preview(
    service: str,
    action: str,
    target: str,
    body: str,
    subject: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Formats a structured outbound action preview banner."""
    lines = [
        "=" * 80,
        "[OUTBOUND ACTION PREVIEW - APPROVAL REQUIRED]",
        f"Service : {service.upper()}",
        f"Action  : {action}",
        f"Target  : {target}",
    ]
    if subject is not None:
        lines.append(f"Subject : {subject}")
    if extra:
        for k, v in extra.items():
            lines.append(f"{k.capitalize():<8}: {v}")

    lines.append("-" * 80)
    lines.append("Payload Body:")
    lines.append(body.strip() if body else "(empty)")
    lines.append("-" * 80)
    lines.append("Status  : DRY RUN (NO outbound message sent)")
    lines.append("Action  : Show this preview to user. Run with '--confirm' only after explicit approval.")
    lines.append("=" * 80)
    return "\n".join(lines)


def guard_outbound(
    confirmed: bool,
    service: str,
    action: str,
    target: str,
    body: str,
    subject: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Enforces dry-run preview unless confirmed is True.

    Returns:
        True if confirmed and permitted to dispatch.
        False if dry-run preview was rendered (abort execution).
    """
    if not confirmed:
        print(render_preview(service, action, target, body, subject=subject, extra=extra))
        return False
    return True

