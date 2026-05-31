import argparse
from pathlib import Path

from app.database import session_scope
from app.services.website_scraper import scrape_from_json


def main() -> None:
    """CLI entrypoint for scraping enabled property websites into local text files."""
    parser = argparse.ArgumentParser(description="Scrape configured property websites to local text files.")
    parser.add_argument("--json-path", required=True)
    parser.add_argument("--include-medium-confidence", action="store_true")
    args = parser.parse_args()
    with session_scope() as db:
        summary = scrape_from_json(db, Path(args.json_path), high_confidence_only=not args.include_medium_confidence)
    print(summary.as_dict())


if __name__ == "__main__":
    main()
