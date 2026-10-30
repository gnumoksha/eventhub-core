"""
Export the OpenAPI schema to a JSON file.

This is useful for the front-end to generate API clients and
it is better than downloading the schema from the running server because that
version is a single line that is hard for LLMs to read.

https://github.com/fastapi/fastapi/discussions/7690#discussioncomment-8734825
"""

import json
from pathlib import Path

from eventhub_core.main import app

OUTPUT_FILE = Path(__file__).parent.parent / "openapi.json"
OUTPUT_FILE.write_text(json.dumps(app.openapi(), indent=2))
