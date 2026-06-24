"""demo.services.api_gateway — the ``api-gateway`` edge service (fans out to all 4)."""

from __future__ import annotations

from demo.app.factory import create_app

app = create_app("api-gateway")
