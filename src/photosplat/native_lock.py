"""Export a portable Conda explicit file, including hashes and no local prefix."""

import argparse
import json
from pathlib import Path


def export(prefix: Path, output: Path):
    packages = []
    for file in sorted((prefix / "conda-meta").glob("*.json")):
        record = json.loads(file.read_text())
        url = record.get("url")
        checksum = record.get("md5")
        if not url or not checksum:
            raise ValueError(f"Missing source URL/hash for package metadata {file.name}")
        packages.append(f"{url}#{checksum}")
    if not packages:
        raise ValueError("This is not an installed Conda/micromamba prefix.")
    output.write_text("# platform: linux-64\n@EXPLICIT\n" + "\n".join(packages) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("prefix", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.prefix, args.output)
