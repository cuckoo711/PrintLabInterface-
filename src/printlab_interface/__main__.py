"""`python -m printlab_interface` or the `printlab-interface` script."""
from __future__ import annotations

import uvicorn

from .app import create_app
from .config import load_settings


def main() -> None:
    settings = load_settings()
    # Loopback only; there is no authentication yet (see config.load_settings).
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
