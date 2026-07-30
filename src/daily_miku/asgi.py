"""Production ASGI application entrypoint."""

from .http import create_app

app = create_app()
