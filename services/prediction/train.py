import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import zipfile

from app.config import settings
from app.training import train_model_from_csv


def parse_args():
    parser = argparse.ArgumentParser(description="Train and evaluate AirGuard's Random Forest.")
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--csv-path", help="A CSV for one room.")
    sources.add_argument("--zip-path", help="A ZIP containing exactly one CSV.")
    sources.add_argument("--room-id", help="Fetch this room's history from the configured Adaptor.")
    parser.add_argument("--output-path", default=settings.model_path)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--max-samples", type=int, default=25000)
    return parser.parse_args()


def main():
    args = parse_args()
    with ExitStack() as stack:
        csv_path = args.csv_path
        if args.zip_path:
            archive = stack.enter_context(zipfile.ZipFile(args.zip_path))
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError("ZIP must contain exactly one CSV; otherwise use --csv-path")
            folder = stack.enter_context(tempfile.TemporaryDirectory(prefix="airguard-training-"))
            csv_path = str(Path(folder) / "data.csv")
            Path(csv_path).write_bytes(archive.read(names[0]))
        if args.room_id:
            from app.main import build_service
            import pandas as pd
            response = build_service().clients.thingspeak.fetch_history(args.room_id, 288)
            if not response.points:
                raise ValueError(f"No historical data for room {args.room_id}")
            folder = stack.enter_context(tempfile.TemporaryDirectory(prefix="airguard-training-"))
            csv_path = str(Path(folder) / "room-history.csv")
            pd.DataFrame([point.model_dump() for point in response.points]).to_csv(csv_path, index=False)
        stats = train_model_from_csv(csv_path, args.output_path, args.horizon_minutes, args.max_samples)
        print(f"Saved trained model to {args.output_path}")
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
