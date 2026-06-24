"""demo.services — the 5 FastAPI app entrypoints (one ``app`` object per module).

Each module exposes a module-level ``app = create_app("<service>")`` so uvicorn can
target ``demo.services.<module>:app``. Module names use underscores (Python
identifier rule); the service names passed to ``create_app`` use the LOCKED hyphen
form where applicable (``api-gateway``).
"""
