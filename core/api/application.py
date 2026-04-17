"""Application bootstrap for the Maverick v3 core."""


def create_application() -> dict[str, str]:
    """Return a minimal application descriptor for the core bootstrap."""
    return {"name": "maverick-core", "status": "initialized"}
