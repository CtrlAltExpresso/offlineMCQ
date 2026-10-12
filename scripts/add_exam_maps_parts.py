#!/usr/bin/env python3
"""Append the recovered per-exam question maps (api_data/exam_maps) to an
already-built content bundle as NEW parts, without re-touching the existing
parts on the server.

The viewer fetches ../api_data/exam_maps/exam_<id>.json, but the original
bundle build (make_content_bundle.py) only packaged viewer/ + media host
dirs, so every exam 404'd and the viewer showed "This exam is locked".

This script reads the existing manifest, packs api_data/exam_maps/exam_*.json
into fresh part_0018.zip... parts, appends them to the manifest, and bumps
the manifest version. The Android app detects the version bump and re-syncs
only the new parts (already-downloaded parts are skipped via their .ok
markers).

Usage:
  python3 scripts/add_exam_maps_parts.py [--out DIR] [--part-size MB]
"""

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAM_MAPS = ROOT / "api_data" / "exam_maps"
SIZE_MB = 512


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/sakib/android_apk_build/bundle")
    ap.add_argument("--part-size", type=int, default=SIZE_MB)
    ap.add_argument("--version", type=int, default=0,
                    help="manifest version; default = current manifest version + 1")
    ap.add_argument("--prev-manifest", default="",
                    help="previously PUBLISHED manifest; unchanged parts get \"carry\": true")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.exists():
        raise SystemExit(f"bundle dir not found: {out}")

    manifest_path = out / "livemcq_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # This used to hardcode version 2, which silently DOWNGRADED a newer
    # manifest (ContentManager.checkForUpdate only accepts a strictly greater
    # version, so the rebuilt bundle would never reach installed apps).
    prev_version = int(manifest.get("version", 0))
    new_version = args.version or (prev_version + 1)
    if new_version <= prev_version:
        print(f"warning: version {new_version} is not greater than the existing"
              f" {prev_version}; installed apps will NOT pick it up")

    prev_parts = {}
    if args.prev_manifest:
        pp = Path(args.prev_manifest)
        if pp.exists():
            try:
                prev_parts = {p["file"]: p for p in
                              json.loads(pp.read_text(encoding="utf-8")).get("parts", [])}
                print(f"diffing against {pp} ({len(prev_parts)} parts)")
            except Exception as e:
                print(f"warning: could not read {pp}: {e}")

    files = sorted(p for p in EXAM_MAPS.glob("exam_*.json") if p.is_file())
    if not files:
        raise SystemExit(f"no exam_*.json under {EXAM_MAPS}")
    total_src = sum(os.stat(f).st_size for f in files)
    print(f"{len(files)} exam maps, {total_src/1073741824:.2f} GB uncompressed")

    start_idx = len(manifest["parts"])
    limit = args.part_size * 1024 * 1024

    new_parts = []
    idx = start_idx
    cur = None
    cur_bytes = 0
    cur_names = []

    def flush(idx, cur_names, cur_bytes):
        if not cur_names:
            return
        pz = out / f"part_{idx:04d}.zip"
        if pz.exists():
            pz.unlink()
        with zipfile.ZipFile(pz, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for src, arc in cur_names:
                z.write(src, arc)
        h = hashlib.sha256(pz.read_bytes()).hexdigest()
        entry = {"file": pz.name, "size": pz.stat().st_size, "sha256": h, "count": len(cur_names)}
        # Same filename and bytes as the published bundle => a device that already
        # holds it (even with a pre-hash "ok" marker) can skip the re-download.
        if prev_parts.get(pz.name, {}).get("sha256") == h:
            entry["carry"] = True
        new_parts.append(entry)
        print(f"  {pz.name}: {pz.stat().st_size/1048576:.0f} MB  {len(cur_names)} files"
              f"{'  [carry]' if entry.get('carry') else ''}")

    for f in files:
        sb = os.stat(f).st_size
        if cur_bytes and cur_bytes + sb > limit:
            flush(idx, cur_names, cur_bytes)
            idx += 1
            cur_bytes = 0
            cur_names = []
        cur_names.append((f, f"api_data/exam_maps/{f.name}"))
        cur_bytes += sb
    flush(idx, cur_names, cur_bytes)

    if not new_parts:
        raise SystemExit("no new parts produced")

    manifest["parts"].extend(new_parts)
    manifest["total_bytes"] = manifest.get("total_bytes", 0) + total_src
    manifest["total_files"] = manifest.get("total_files", 0) + len(files)
    manifest["version"] = new_version
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    print(f"\nmanifest: {manifest_path}")
    print(f"version:     {prev_version} -> {manifest['version']}")
    print(f"total parts: {len(manifest['parts'])}")
    print(f"total bytes: {manifest['total_bytes']/1073741824:.2f} GB")
    print(f"total files: {manifest['total_files']}")


if __name__ == "__main__":
    main()