"""Write PBIR folder structure from transformed workbook dict."""

from pathlib import Path


def generate(transformed: dict, output_dir: Path) -> Path:
    """Write PBIR output folders. Stub for T1."""
    name = transformed["name"]
    report_dir = output_dir / f"{name}.Report"
    model_dir = output_dir / f"{name}.SemanticModel"
    report_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    return report_dir
