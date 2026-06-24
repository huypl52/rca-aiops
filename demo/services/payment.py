"""demo.services.payment — the ``payment`` leaf microservice."""

from __future__ import annotations

from demo.app.factory import create_app

app = create_app("payment")
