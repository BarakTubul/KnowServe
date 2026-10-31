"""Print the OpenAPI schema generated from the app with default settings (contract: api.md).

Usage: ``uv run python -m knowserve_api.export_openapi > docs/contracts/openapi.json``
"""

from __future__ import annotations

import json
import sys
from typing import Any

from knowserve_core.settings import Settings

from .app import create_app


def build_schema() -> dict[str, Any]:
    # Explicit arguments take priority over the environment, so the schema is reproducible.
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://schema:schema@localhost/schema",
        env="local",
        api_allowed_origins=["http://localhost:5173"],
        enable_spike_endpoints=False,
    )
    return create_app(settings).openapi()


def main() -> None:
    sys.stdout.write(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
