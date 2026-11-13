"""Named, static public affordability resources.

These are fixed, published programmes, not generated suggestions. The app points to
them and then asks for a conversation with a doctor or pharmacist; it never ends at
"here is a cheaper option." Verify the links are current before any real deployment.
"""

import json
from functools import lru_cache
from pathlib import Path

RESOURCES_PATH = Path(__file__).resolve().parent.parent / "data" / "affordability-resources.json"


@lru_cache(maxsize=1)
def affordability_resources() -> list[dict[str, str]]:
    raw = json.loads(RESOURCES_PATH.read_text(encoding="utf-8"))
    return raw["resources"]
