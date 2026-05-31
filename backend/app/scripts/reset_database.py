from app.database import Base, engine, init_db


def main() -> None:
    """CLI entrypoint for dropping and recreating all Asset AI tables."""
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    init_db()
    print({"status": "database reset", "database_url": engine.url.render_as_string(hide_password=True)})


if __name__ == "__main__":
    main()
