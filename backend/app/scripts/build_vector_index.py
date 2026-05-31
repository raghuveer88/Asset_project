from app.database import session_scope
from app.services.vector_index import rebuild_index


def main() -> None:
    """CLI entrypoint for rebuilding the scoped Chroma website-content index."""
    with session_scope() as db:
        print(rebuild_index(db))


if __name__ == "__main__":
    main()
