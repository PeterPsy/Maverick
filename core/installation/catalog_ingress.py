"""Public static product distribution routes shared by installer and host worker."""

from pathlib import Path
import re


def render_catalog_locations(repository_root: Path) -> str:
    root = str(repository_root)
    if not repository_root.is_absolute() or not re.fullmatch(r"/[A-Za-z0-9_./-]+", root):
        raise ValueError("Catalog ingress requires a safe absolute installation path")
    return f'''    location = /catalog/api/apps {{
        alias {root}/installation/catalog/api/apps;
        default_type application/json;
        add_header Cache-Control "no-cache";
        add_header X-Content-Type-Options "nosniff" always;
    }}
    location ~ "^/catalog/artifacts/(?<loopino_catalog_file>[a-z0-9-]+-[A-Za-z0-9._+-]+-[a-f0-9]{{64}}\\.tar\\.gz(?:\\.manifest\\.json)?)$" {{
        alias {root}/installation/catalog/artifacts/$loopino_catalog_file;
        default_type application/octet-stream;
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header X-Content-Type-Options "nosniff" always;
    }}
    location /catalog/ {{ return 404; }}
'''
