"""demo.services.order — the ``order`` service (depends on inventory + payment)."""

from __future__ import annotations

from demo.app.factory import create_app

app = create_app("order")
