import argparse
from pathlib import Path

from app.database import session_scope
from app.services.rent_roll_ingestion import ingest_zip


def main() -> None:
    """CLI entrypoint for ingesting rent-roll zip files into scoped MySQL tables."""
    parser = argparse.ArgumentParser(description="Ingest rent-roll Excel files from a zip into MySQL.")
    parser.add_argument("--zip-path", required=True)
    args = parser.parse_args()
    with session_scope() as db:
        summary = ingest_zip(db, Path(args.zip_path))
    print(summary.as_dict())


if __name__ == "__main__":
    main()
