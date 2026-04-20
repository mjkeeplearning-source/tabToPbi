"""CLI entry point: parse → transform → generate."""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from tab_to_pbi.parser import parse
from tab_to_pbi.transformer import transform
from tab_to_pbi.generator import generate
from tab_to_pbi.translator import translate_calc_fields_in_transformed

load_dotenv()


def _dump(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"Debug: {path}")


def main():
    if len(sys.argv) != 2:
        print("Usage: uv run tab_to_pbi/main.py <path/to/workbook.twb>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    data_dir = input_path.parent.parent / "data"

    workbook = parse(input_path)
    _dump(workbook, output_dir / f"{input_path.stem}.parsed.json")

    transformed = transform(workbook)
    transformed = translate_calc_fields_in_transformed(transformed)
    _dump(transformed, output_dir / f"{input_path.stem}.transformed.json")

    report_path = generate(transformed, output_dir, data_dir)

    report_file = output_dir / f"{input_path.stem}.migration_report.json"
    report_file.write_text(json.dumps(transformed.get("report", {}), indent=2))

    print(f"Output: {report_path}")
    print(f"Report: {report_file}")

    from tab_to_pbi.validator import validate, print_results
    results = validate(report_path)
    print()
    print_results(report_path, results)
    if any(r.level == "ERROR" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
