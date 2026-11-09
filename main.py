from pathlib import Path

from finance_app.ui import create_application


def main() -> None:
    database_path = Path.home() / ".finsim" / "simulation.sqlite3"
    create_application(database_path)


if __name__ == "__main__":
    main()
