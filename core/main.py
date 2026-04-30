"""Maverick core bootstrap entrypoint."""

from core.api.application import create_application


app = create_application()


def main() -> None:
    """Build the core application."""
    create_application()


if __name__ == "__main__":
    main()
