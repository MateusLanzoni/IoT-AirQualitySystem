from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.training import load_dataset


def parse_args():
    parser = argparse.ArgumentParser(description="Prepare aggregated historical data for the mock ThingSpeak Adapter.")
    parser.add_argument("--csv-path", help="Path to the source CSV file.")
    parser.add_argument("--zip-path", help="Path to a ZIP archive containing the source CSV file.")
    parser.add_argument(
        "--output-path",
        default=str(Path(__file__).resolve().parents[3] / "data" / "aggregated_iaq_history.csv"),
        help="Where to write the aggregated CSV.",
    )
    return parser.parse_args()


def extract_csv_from_zip(zip_path: str) -> str:
    archive = zipfile.ZipFile(zip_path)
    csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if not csv_names:
        raise ValueError("No CSV file found in archive")

    temp_dir = tempfile.mkdtemp(prefix="airguard-mock-data-")
    return archive.extract(csv_names[0], path=temp_dir)


def main():
    args = parse_args()
    csv_path = args.csv_path
    if not csv_path:
        if not args.zip_path:
            raise ValueError("Provide either --csv-path or --zip-path")
        csv_path = extract_csv_from_zip(args.zip_path)

    df = load_dataset(csv_path)
    aggregated = (
        df.groupby("timestamp")[["temperature", "humidity", "pm25", "co2"]]
        .mean()
        .sort_index()
        .resample("5min")
        .mean()
        .interpolate(limit_direction="both")
        .dropna()
        .reset_index()
    )

    output = Path(args.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    aggregated.to_csv(output, index=False)
    print(f"Saved aggregated mock history to {output}")
    print({"rows": len(aggregated), "columns": list(aggregated.columns)})


if __name__ == "__main__":
    main()
