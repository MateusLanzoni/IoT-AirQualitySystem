import argparse
import tempfile
import zipfile
from pathlib import Path

from app.training import train_model_from_csv


def parse_args():
    parser = argparse.ArgumentParser(description="Train the AirGuard prediction model from the IoT dataset.")
    parser.add_argument("--csv-path", help="Path to the source CSV file.")
    parser.add_argument("--zip-path", help="Path to a ZIP archive containing the source CSV file.")
    parser.add_argument(
        "--output-path",
        default=str(Path(__file__).parent / "model" / "model.joblib"),
        help="Where to write the trained model.",
    )
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--max-samples", type=int, default=25000)
    return parser.parse_args()


def extract_csv_from_zip(zip_path: str) -> str:
    archive = zipfile.ZipFile(zip_path)
    csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if not csv_names:
        raise ValueError("No CSV file found in archive")

    temp_dir = tempfile.mkdtemp(prefix="airguard-train-")
    csv_path = archive.extract(csv_names[0], path=temp_dir)
    return csv_path


def main():
    args = parse_args()
    csv_path = args.csv_path
    if not csv_path:
        if not args.zip_path:
            raise ValueError("Provide either --csv-path or --zip-path")
        csv_path = extract_csv_from_zip(args.zip_path)

    stats = train_model_from_csv(
        csv_path=csv_path,
        output_path=args.output_path,
        horizon_minutes=args.horizon_minutes,
        max_samples=args.max_samples,
    )
    print(f"Saved trained model to {args.output_path}")
    print(stats)


if __name__ == "__main__":
    main()
