"""Bounded browser actions without introducing a browser runtime dependency."""

from __future__ import annotations

import webbrowser
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit


class BrowserAdapter:
    """Open URLs through the user's default browser or delegate UIA actions."""

    def __init__(
        self,
        ui_automation: Any | None = None,
        opener: Callable[..., bool] | None = None,
    ):
        self.ui_automation = ui_automation
        self.opener = opener or webbrowser.open

    def act(self, operation: str, target: dict[str, Any], value: str | None = None) -> dict[str, Any]:
        if operation in {"open_url", "navigate"}:
            url = target.get("url") or value
            if not isinstance(url, str):
                return {"status": "denied", "reason": "url_required"}
            parts = urlsplit(url.strip())
            if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
                return {"status": "denied", "reason": "only_http_https_urls_without_credentials_are_allowed"}
            accepted = bool(self.opener(url, new=2, autoraise=True))
            safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            return {
                "status": "verified" if accepted else "dispatched",
                "verified": accepted,
                "operation": operation,
                "url": safe_url,
            }

        if self.ui_automation is None:
            return {"status": "degraded", "reason": "browser_ui_automation_unavailable"}
        return self.ui_automation.act(operation, target, value)

