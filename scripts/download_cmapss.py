"""Download NASA C-MAPSS FD001 and verify it.

The official distribution is a zip on the NASA Prognostics Center of Excellence
data repository. Hosts that are unreachable are skipped and the next source is
tried. Files are accepted only if their SHA-256 matches the values below, which
were recorded from a copy checked against the official dataset description
(100 training engines / 20,631 rows, 100 test engines / 13,096 rows, 100 RUL
values, identical first record).

    python scripts/download_cmapss.py --dest datasets/raw/cmapss
Exit code 0 when all three files are present and verified.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

FILES = {
    "train_FD001.txt": "963b5e22825b34d8b21c69e1aeb4af3e647050eb672ee8834ba4b5d91d2de0f8",
    "test_FD001.txt": "3cda7109ce17bafb5443f2ac926cfcf88154b941b8c4cf95eb55d1ddd6f52851",
    "RUL_FD001.txt": "a19c8ec94931949d0485bdc35118206e9c81c4547b422efb9cf86f4ceddbceca",
}
ZIP_SOURCES = [
    "https://phm-datasets.s3.amazonaws.com/NASA/6.+Turbofan+Engine+Degradation+Simulation+Data+Set.zip",
]
RAW_SOURCES = [
    # public mirror of the unmodified NASA text files (verified by checksum)
    "https://raw.githubusercontent.com/hankroark/Turbofan-Engine-Degradation/master/CMAPSSData/{name}",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - fixed https URLs above
        return r.read()


def verified(dest: Path) -> bool:
    return all((dest / n).exists() and sha256((dest / n).read_bytes()) == h for n, h in FILES.items())


def from_zip(dest: Path) -> bool:
    for url in ZIP_SOURCES:
        try:
            outer = zipfile.ZipFile(io.BytesIO(fetch(url, 120)))
        except Exception as exc:  # noqa: BLE001 - try the next source
            print(f"  skip {url}: {exc}")
            continue
        blobs = {Path(n).name: outer.read(n) for n in outer.namelist()}
        inner = next((b for n, b in blobs.items() if n.lower().startswith("cmapssdata") and n.endswith(".zip")), None)
        if inner:
            z = zipfile.ZipFile(io.BytesIO(inner))
            blobs.update({Path(n).name: z.read(n) for n in z.namelist()})
        for name, digest in FILES.items():
            if name in blobs and sha256(blobs[name]) == digest:
                (dest / name).write_bytes(blobs[name])
        if verified(dest):
            return True
    return False


def from_raw(dest: Path) -> bool:
    for pattern in RAW_SOURCES:
        for name, digest in FILES.items():
            if (dest / name).exists() and sha256((dest / name).read_bytes()) == digest:
                continue
            try:
                data = fetch(pattern.format(name=name))
            except Exception as exc:  # noqa: BLE001
                print(f"  skip {pattern.format(name=name)}: {exc}")
                break
            if sha256(data) != digest:
                print(f"  checksum mismatch for {name} from {pattern}; ignored")
                break
            (dest / name).write_bytes(data)
        if verified(dest):
            return True
    return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dest", type=Path, default=Path("datasets/raw/cmapss"))
    a = p.parse_args()
    a.dest.mkdir(parents=True, exist_ok=True)
    if verified(a.dest):
        print(f"C-MAPSS FD001 already present and verified in {a.dest}")
        return 0
    print("Downloading NASA C-MAPSS FD001 ...")
    if from_zip(a.dest) or from_raw(a.dest):
        print(f"C-MAPSS FD001 downloaded and verified in {a.dest}")
        return 0
    print("Could not obtain verified C-MAPSS files. Download them manually (see datasets/README.md).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
