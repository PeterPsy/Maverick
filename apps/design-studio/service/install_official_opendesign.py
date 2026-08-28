#!/usr/bin/env python3
"""Install the selected official OpenDesign OCI release by pinned digest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from official_opendesign_release import (
    OfficialReleaseError,
    install_official_release,
    load_official_release,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--release",
        type=Path,
        default=Path(__file__).with_name("opendesign_official_release.json"),
    )
    args = parser.parse_args()

    release = load_official_release(args.release)
    installation = install_official_release(args.destination, release=release)
    print(
        json.dumps(
            {
                "ok": True,
                "kind": "official_opendesign_installation",
                "image": release.image,
                "version": release.version,
                "manifest_digest": release.manifest_digest,
                "customizations": [],
                "rootfs": str(installation.rootfs),
                "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except OfficialReleaseError as error:
        raise SystemExit(str(error)) from error
