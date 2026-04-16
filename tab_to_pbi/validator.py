"""Validate PBIR output folder structure, JSON schemas, and semantic consistency."""

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"
_DEFAULT_CACHE = Path(".pbir_schema_cache")

SCHEMAS = {
    "definition.pbir": f"{_SCHEMA_BASE}/definitionProperties/2.0.0/schema.json",
    "version.json": f"{_SCHEMA_BASE}/definition/versionMetadata/1.0.0/schema.json",
    "report.json": f"{_SCHEMA_BASE}/definition/report/1.0.0/schema.json",
    "page.json": f"{_SCHEMA_BASE}/definition/page/1.0.0/schema.json",
    "visual.json": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
}


@dataclass
class ValidationResult:
    level: str    # "ERROR" or "WARNING"
    file: str     # relative path shown in output
    message: str


def load_schema(url: str, cache_dir: Path = _DEFAULT_CACHE) -> dict:
    """Fetch JSON schema from url, caching locally under cache_dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = url.replace("https://", "").replace("/", "-").replace(".", "-")
    cache_file = cache_dir / f"{slug}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    with urllib.request.urlopen(url) as resp:
        data = resp.read().decode()
    cache_file.write_text(data)
    return json.loads(data)
