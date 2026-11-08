"""Apply reviewed, versioned schema changes. Never invoked implicitly by web workers."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def main():
    root = Path(__file__).resolve().parents[2]
    command.upgrade(Config(str(root / "alembic.ini")), "head")


if __name__ == "__main__":
    main()
