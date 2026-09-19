"""Official app backend. The anonymous public server never imports this module."""
from external_apps.surfaces import run

if __name__ == "__main__":
    run("backend")
