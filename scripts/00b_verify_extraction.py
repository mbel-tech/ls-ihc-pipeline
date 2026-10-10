"""Stage 0b - verify the extracted CZIs against the zip central directories.

The transfer zips are STORED, so every member's uncompressed size and CRC are
already recorded in the central directory and can be checked without reading a
single byte of the archives.

Size checking is the default and is nearly free. --crc additionally verifies
content, which means reading every extracted file end to end (~420 GB), so it
is opt-in.

Run:  python 00b_verify_extraction.py
      python 00b_verify_extraction.py --crc        # slow, full content check
      python 00b_verify_extraction.py --watch      # poll until extraction ends
"""

import csv
import glob
import importlib.util
import json
import os
import sys
import time
import zipfile
import zlib
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402

SOURCE_DIR = CONFIG["source_dir"]
OUT_ROOT = CONFIG["out_root"]
QC_DIR = os.path.join(OUT_ROOT, "qc")

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

# check()'s columns, pinned: an inventory with nothing in it must still
# leave a file with a header rather than crash on rows[0].
STATUS_KEYS = ["file", "zip", "expected_bytes", "actual_bytes", "status", "crc_ok"]

WATCH_INTERVAL_S = 60
CRC_CHUNK = 1 << 24


def zip_inventory():
    """member filename -> {size, crc, zip} for every CZI in every transfer zip."""
    inventory = {}
    for zpath in sorted(glob.glob(os.path.join(SOURCE_DIR, "*.zip"))):
        try:
            zf = zipfile.ZipFile(zpath)
        except zipfile.BadZipFile:
            print(f"  !! unreadable archive: {os.path.basename(zpath)}")
            continue
        with zf:
            for info in zf.infolist():
                name = os.path.basename(info.filename)
                if not name.lower().endswith(".czi"):
                    continue
                if name in inventory and inventory[name]["size"] != info.file_size:
                    print(f"  !! {name} differs between archives - keeping first")
                    continue
                inventory.setdefault(
                    name,
                    {
                        "size": info.file_size,
                        "crc": info.CRC,
                        "zip": os.path.basename(zpath),
                        "compress_type": info.compress_type,
                    },
                )
    return inventory


def file_crc(path):
    crc = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CRC_CHUNK)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def check(inventory, do_crc=False):
    rows = []
    for name, meta in sorted(inventory.items()):
        path = os.path.join(SOURCE_DIR, name)
        row = {
            "file": name,
            "zip": meta["zip"],
            "expected_bytes": meta["size"],
            "actual_bytes": "",
            "status": "",
            "crc_ok": "",
        }
        if not os.path.exists(path):
            row["status"] = "missing"
        else:
            actual = os.path.getsize(path)
            row["actual_bytes"] = actual
            if actual != meta["size"]:
                # A file still being written is short, not corrupt.
                row["status"] = "in_progress" if actual < meta["size"] else "size_mismatch"
            else:
                row["status"] = "ok"
                if do_crc:
                    row["crc_ok"] = int(file_crc(path) == meta["crc"])
                    if not row["crc_ok"]:
                        row["status"] = "crc_mismatch"
        rows.append(row)
    return rows


def summarise(rows, inventory):
    counts = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1

    total_bytes = sum(m["size"] for m in inventory.values())
    done_bytes = sum(r["actual_bytes"] or 0 for r in rows if r["status"] == "ok")
    return counts, total_bytes, done_bytes


def report(rows, inventory, do_crc):
    counts, total_bytes, done_bytes = summarise(rows, inventory)
    print()
    print("=" * 72)
    print(f"CZIs listed in the archives : {len(rows)}")
    for status in ("ok", "in_progress", "missing", "size_mismatch", "crc_mismatch"):
        if counts.get(status):
            print(f"  {status:<14}: {counts[status]}")
    print(
        f"extracted so far            : {done_bytes / 1e9:.1f} GB of {total_bytes / 1e9:.1f} GB "
        f"({100.0 * done_bytes / max(total_bytes, 1):.1f}%)"
    )

    bad = [r for r in rows if r["status"] in ("size_mismatch", "crc_mismatch")]
    if bad:
        print(f"\n  CORRUPT - re-extract these {len(bad)}:")
        for r in bad[:20]:
            print(f"    {r['file']}  from {r['zip']}  ({r['actual_bytes']} vs {r['expected_bytes']})")

    pending = [r for r in rows if r["status"] in ("missing", "in_progress")]
    if pending:
        remaining = sum(
            inventory[r["file"]]["size"] - (r["actual_bytes"] or 0) for r in pending
        )
        print(f"\n  still to extract: {len(pending)} files, {remaining / 1e9:.1f} GB")
        by_zip = defaultdict(int)
        for r in pending:
            by_zip[r["zip"]] += 1
        for z, n in sorted(by_zip.items(), key=lambda kv: -kv[1]):
            print(f"    {n:>3} from {z}")
    elif not bad:
        print("\n  extraction complete and every size matches." + ("" if do_crc else "  (run --crc to verify content)"))
    print("=" * 72)
    return counts


def main():
    do_crc = "--crc" in sys.argv
    watch = "--watch" in sys.argv

    print(f"Reading zip central directories in {SOURCE_DIR} ...")
    inventory = zip_inventory()
    stored = sum(1 for m in inventory.values() if m["compress_type"] == 0)
    print(f"  {len(inventory)} CZI members ({stored} STORED)")

    while True:
        rows = check(inventory, do_crc)
        counts = report(rows, inventory, do_crc)

        os.makedirs(QC_DIR, exist_ok=True)
        out = os.path.join(QC_DIR, "extraction_status.csv")
        IO.atomic_write_csv(out, rows, STATUS_KEYS)
        print(f"  wrote {out}")

        if not watch or not (counts.get("missing") or counts.get("in_progress")):
            break
        print(f"  waiting {WATCH_INTERVAL_S}s ...\n")
        time.sleep(WATCH_INTERVAL_S)


if __name__ == "__main__":
    main()
