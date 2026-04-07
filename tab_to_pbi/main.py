"""CLI entry point: parse → transform → generate."""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from tab_to_pbi.parser import parse
from tab_to_pbi.transformer import transform
from tab_to_pbi.generator import generate

load_dotenv()


def main():
    if len(sys.argv) != 2:
        print("Usage: uv run tab_to_pbi/main.py <path/to/workbook.twb>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    workbook = parse(input_path)
    transformed = transform(workbook)
    report_path = generate(transformed, output_dir)

    report_file = output_dir / f"{input_path.stem}.migration_report.json"
    report_file.write_text(json.dumps(transformed.get("report", {}), indent=2))

    print(f"Output: {report_path}")
    print(f"Report: {report_file}")


if __name__ == "__main__":
    main()
