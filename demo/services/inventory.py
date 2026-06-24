"""demo.services.inventory — the ``inventory`` leaf microservice."""

from __future__ import annotations

from demo.app.factory import create_app

app = create_app("inventory")
