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


def _find_model_dir(report_dir: Path) -> Path | None:
    """Find the sibling SemanticModel directory."""
    candidates = list(report_dir.parent.glob("*.SemanticModel"))
    return candidates[0] if candidates else None


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


def check_presence(report_dir: Path) -> list[ValidationResult]:
    """Phase 1: verify all required files and folders exist."""
    results = []

    def err(msg: str) -> None:
        results.append(ValidationResult("ERROR", str(report_dir), msg))

    model_dir = _find_model_dir(report_dir)

    if not (report_dir / "definition.pbir").exists():
        err("Missing required file: definition.pbir")

    defn_dir = report_dir / "definition"
    if not defn_dir.is_dir():
        err("Missing required folder: definition/")
        if model_dir and not (model_dir / "model.bim").exists():
            err("Missing required file: model.bim")
        if model_dir and not (model_dir / "definition.pbism").exists():
            err("Missing required file: definition.pbism")
        return results

    if not (defn_dir / "version.json").exists():
        err("Missing required file: definition/version.json")
    if not (defn_dir / "report.json").exists():
        err("Missing required file: definition/report.json")

    pages_dir = defn_dir / "pages"
    if not pages_dir.is_dir() or not any(pages_dir.iterdir()):
        err("Missing required folder with pages: definition/pages/")
    else:
        for page_dir in pages_dir.iterdir():
            if page_dir.is_dir() and not (page_dir / "page.json").exists():
                err(f"Missing required file: {page_dir.relative_to(report_dir.parent)}/page.json")

    if model_dir is None:
        err("Missing SemanticModel directory (expected sibling of Report folder)")
    else:
        if not (model_dir / "model.bim").exists():
            err("Missing required file: model.bim")
        if not (model_dir / "definition.pbism").exists():
            err("Missing required file: definition.pbism")

    return results
