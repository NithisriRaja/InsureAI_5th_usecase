"""Write the API's OpenAPI schema to a file (used by the frontend's `npm run gen:api`).

python -m backend.scripts.export_openapi openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from main import app


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"OpenAPI schema written to {out}")


if __name__ == "__main__":
    main()
