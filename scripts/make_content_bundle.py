#!/usr/bin/env python3
"""Package the recovered viewer + media into resumable-on-device .zip parts.

Output layout (one directory, ready to upload to any plain HTTPS host —
archive.org, a VPS, etc.):

    <out>/
      livemcq_manifest.json   # app fetches this; it points at the parts
      part_0000.zip ...       # <= PART_SIZE each, zip of safe relative paths
          viewer/...          # the web app (deflate-compressed)
          assets.livemcq.com/...            # media, stored raw (incompressible)
          files.livemcq.app/...
          elasticbeanstalk-ap-southeast-1-051040323559.s3.amazonaws.com/...

The app streams the manifest, downloads parts (with range-resume + sha256
verification), extracts them under its internal files dir, then serves the
whole tree from a loopback HTTP server — full offline afterwards.

Usage:
  python3 scripts/make_content_bundle.py [--out DIR] [--part-size MB]
"""

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
VIEWER = ROOT / "viewer"

HOST_DIRS = [
    "assets.livemcq.com",
    "files.livemcq.app",
    "elasticbeanstalk-ap-southeast-1-051040323559.s3.amazonaws.com",
]

SIZE_MB = 512


def iter_files():
    for host in HOST_DIRS:
        base = MEDIA / host
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file():
                yield f, f.relative_to(MEDIA).as_posix()
    for f in sorted(VIEWER.rglob("*")):
        if f.is_file() and f.name not in ("livemcq.db", "serve.py"):
            yield f, f"viewer/{f.relative_to(VIEWER).as_posix()}"


def compressible(path):
    return path.startswith("viewer/") or path.lower().endswith(
        (".txt", ".json", ".js", ".css", ".html", ".svg", ".xml")
    )


def part_zip_path(out, idx):
    return out / f"part_{idx:04d}.zip"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/sakib/android_apk_build/bundle")
    ap.add_argument("--part-size", type=int, default=SIZE_MB)
    ap.add_argument("--version", type=int, default=0,
                    help="manifest version; default = previous manifest version + 1")
    ap.add_argument("--prev-manifest", default="",
                    help="previously PUBLISHED manifest to diff against; parts whose "
                         "bytes are unchanged get \"carry\": true so devices that already "
                         "hold them skip the re-download (defaults to the manifest in --out)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    limit = args.part_size * 1024 * 1024

    # ContentManager.checkForUpdate() only re-syncs when the remote version is
    # strictly greater than what the device stored, so a rebuild must never
    # reuse (or lower) the version of the bundle already out in the wild.
    mpath = out / "livemcq_manifest.json"
    prev_version = 0
    if mpath.exists():
        try:
            prev_version = int(json.loads(mpath.read_text(encoding="utf-8")).get("version", 0))
        except Exception:
            prev_version = 0
    version = args.version or (prev_version + 1)
    if args.version and args.version <= prev_version:
        print(f"warning: requested version {version} is not greater than the existing {prev_version};"
              f" installed apps will NOT pick it up")

    # Which parts can a device that has already synced keep? Compare against the
    # manifest that is actually published on the server (the one in --out is the
    # freshly built one, so it is only a fallback).
    prev_parts = {}
    prev_path = Path(args.prev_manifest) if args.prev_manifest else mpath
    if prev_path.exists() and prev_path.resolve() != mpath.resolve():
        try:
            prev_parts = {p["file"]: p for p in json.loads(prev_path.read_text(encoding="utf-8")).get("parts", [])}
        except Exception as e:
            print(f"warning: could not read {prev_path}: {e}")
        else:
            print(f"diffing against {prev_path} ({len(prev_parts)} parts)")

    total_bytes = 0
    parts = []
    idx = 0
    cur = None
    cur_bytes = 0
    cur_count = 0

    files = list(iter_files())
    print(f"{len(files)} files collected")

    def flush(idx, cur_bytes, cur_count, cur_names):
        if cur_names is None:
            return 0
        pz = part_zip_path(out, idx)
        mode = "w"
        if pz.exists():
            pz.unlink()
        with zipfile.ZipFile(pz, mode, compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for src, arc in cur_names:
                store = (cur_bytes > 16 * 1024 * 1024) and not compressible(arc)
                comp = zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED
                z.write(src, arc, compress_type=comp)
        h = hashlib.sha256(pz.read_bytes()).hexdigest()
        entry = {"file": pz.name, "size": pz.stat().st_size, "sha256": h, "count": cur_count}
        # Present in the last published manifest with identical bytes => devices
        # which already hold this part (including pre-hash "ok" markers) can keep
        # it and only fetch what actually changed.
        if prev_parts.get(pz.name, {}).get("sha256") == h:
            entry["carry"] = True
        parts.append(entry)
        # reconstruct byte total for the part's files for reporting (approx)
        print(f"  {pz.name}: {pz.stat().st_size/1048576:.0f} MB  {cur_count} files  sha={h[:12]}"
              f"{'  [carry]' if entry.get('carry') else ''}")
        return 1

    cur_names = []
    for src, arc in files:
        sb = os.stat(src).st_size
        if cur_bytes and cur_bytes + sb > limit:
            flush(idx, cur_bytes, cur_count, cur_names)
            idx += 1
            cur_bytes = 0
            cur_count = 0
            cur_names = []
        cur_names.append((src, arc))
        cur_bytes += sb
        cur_count += 1
        total_bytes += sb
    if cur_names:
        flush(idx, cur_bytes, cur_count, cur_names)

    manifest = {
        "version": version,
        "total_bytes": total_bytes,
        "total_files": len(files),
        "parts": parts,
    }
    mpath.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"\nmanifest: {mpath}  (version {prev_version} -> {version})")
    print(f"parts: {len(parts)}   total bytes: {total_bytes/1073741824:.2f} GB")
    for p in parts:
        print(f"  {p['file']:16} {p['size']/1048576:7.0f} MB  sha256 {p['sha256']}")


if __name__ == "__main__":
    main()