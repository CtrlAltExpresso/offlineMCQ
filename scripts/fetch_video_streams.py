#!/usr/bin/env python3
"""Recover LiveMCQ video stream URLs.

Findings (2026-10-12):
  GET https://livemcq.com/api/v1/get-video-resulation/<id>/
      Authorization: Token <TOKEN>
  ->
      {"video_id": "...", "video_base_url": "https://<cdn-host>/videos/<id>/",
       "list": [{"quality","rendition","type","link","size",...}, ...]}

  The playable URL is simply  <video_base_url> + <link>
      e.g. https://jwbn3t9o8d.tenbytecdn.com/videos/1758037080/1758037080_360p.mp4

  The CDN is NOT authenticated: plain GET/HEAD/Range works, `secret_key` from
  the app's video records is irrelevant (it is a static app-level constant).

This script enumerates every video id found in api_data/video_catalog/**, asks
the API for the rendition list, and writes api_data/video_streams/<id>.json
(resumable: existing valid files are skipped).

Usage:
    LMCQ_TOKEN=xxxxxxxx python3 scripts/fetch_video_streams.py
    ... --aggregate            # also write viewer/data/video_streams.json
    ... --ids 1758037080,123   # only these ids
    ... --workers 8
"""
import argparse
import glob
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "api_data", "video_catalog")
OUT = os.path.join(ROOT, "api_data", "video_streams")
API = "https://livemcq.com/api/v1/get-video-resulation/{id}/"
UA = "Mozilla/5.0 (X11; Linux x86_64) LMCQ-recovery/1.0"

_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a, flush=True)


def video_ids_from_catalog():
    ids = {}
    for f in sorted(glob.glob(os.path.join(CATALOG, "video_*.json"))):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        series = os.path.basename(f)[len("video_"):-len(".json")]
        for v in d.get("videos", []):
            vid = str(v.get("id") or "").strip()
            if vid:
                ids.setdefault(vid, set()).add(series)
    return ids


def valid(path):
    try:
        d = json.load(open(path))
    except Exception:
        return False
    return bool(d.get("video_base_url")) and isinstance(d.get("list"), list)


def fetch(vid, token, tries=4):
    url = API.format(id=vid)
    req = urllib.request.Request(url, headers={
        "Authorization": "Token " + token,
        "Accept": "application/json",
        "User-Agent": UA,
    })
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (400, 403, 404):
                break
        except Exception as e:
            last = type(e).__name__ + ": " + str(e)[:80]
        time.sleep(1.5 * (n + 1))
    raise RuntimeError(last or "failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("LMCQ_TOKEN", ""))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ids", default="")
    ap.add_argument("--aggregate", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    token = args.token.strip()
    if not token:
        sys.exit("missing token: set LMCQ_TOKEN or pass --token")

    os.makedirs(OUT, exist_ok=True)

    if args.ids:
        ids = {i.strip(): set() for i in args.ids.split(",") if i.strip()}
    else:
        ids = video_ids_from_catalog()
        log("catalog: %d unique video ids" % len(ids))

    todo = [v for v in ids if not valid(os.path.join(OUT, v + ".json"))]
    if args.limit:
        todo = todo[:args.limit]
    log("todo: %d (already have %d)" % (len(todo), len(ids) - len(todo)))

    ok = fail = 0
    failures = []
    t0 = time.time()

    def work(vid):
        d = fetch(vid, token)
        d["_id"] = vid
        tmp = os.path.join(OUT, vid + ".json.tmp")
        json.dump(d, open(tmp, "w"), ensure_ascii=False)
        os.replace(tmp, os.path.join(OUT, vid + ".json"))
        return vid, d

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, v): v for v in todo}
        for i, f in enumerate(as_completed(futs), 1):
            v = futs[f]
            try:
                _, d = f.result()
                ok += 1
                tot = sum(r.get("size") or 0 for r in d.get("list", []))
                log("[%d/%d] %s  %d renditions  %.2f GB" % (
                    i, len(todo), v, len(d.get("list", [])), tot / 1e9))
            except Exception as e:
                fail += 1
                failures.append((v, str(e)))
                log("[%d/%d] %s  FAIL %s" % (i, len(todo), v, e))

    log("done: ok=%d fail=%d in %.1fs" % (ok, fail, time.time() - t0))
    if failures:
        fp = os.path.join(OUT, "_failures.tsv")
        with open(fp, "w") as fh:
            for v, e in failures:
                fh.write("%s\t%s\n" % (v, e))
        log("failures -> %s" % fp)

    if args.aggregate:
        aggregate()


def aggregate():
    """Merge api_data/video_streams/*.json -> viewer/data/video_streams.json"""
    cat = video_ids_from_catalog()
    out = {}
    for vid in sorted(cat):
        p = os.path.join(OUT, vid + ".json")
        if not valid(p):
            continue
        d = json.load(open(p))
        base = d.get("video_base_url") or ""
        rends = []
        for r in d.get("list", []):
            link = r.get("link") or ""
            rends.append({
                "rendition": r.get("rendition"),
                "quality": r.get("quality"),
                "type": r.get("type"),
                "w": r.get("width"),
                "h": r.get("height"),
                "size": r.get("size"),
                "url": base + link,
                "file": link,
            })
        out[vid] = {
            "base": base,
            "series": sorted(cat[vid]),
            "renditions": rends,
        }
    dst = os.path.join(ROOT, "viewer", "data", "video_streams.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    json.dump(out, open(dst, "w"), ensure_ascii=False, separators=(",", ":"))
    total = sum(r["size"] or 0 for v in out.values() for r in v["renditions"])
    log("aggregate: %d videos, %d renditions, %.2f TB total -> %s" % (
        len(out), sum(len(v["renditions"]) for v in out.values()),
        total / 1e12, dst))


if __name__ == "__main__":
    main()
