"""Print the OpenAPI schema (used by `npm run gen:api` to generate web/src/api/schema.d.ts)."""

import json

from .main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=1))
