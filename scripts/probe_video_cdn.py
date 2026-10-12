#!/usr/bin/env python3
"""Inventory LiveMCQ video files directly on the CDN (no API, no auth).

Every video id maps to a deterministic, unauthenticated URL:

    https://jwbn3t9o8d.tenbytecdn.com/videos/<id>/<id>_<rendition>.mp4
    rendition in {360p, 540p, 720p}

Verified 2026-10-12 against 195 API responses (100% of sampled videos used this
single base host and this exact rendition set; CDN accepts GET/HEAD/Range with
no token, no Referer, no cookie).

Writes api_data/video_streams/<id>.json using the same shape as the API
responses (plus "source":"cdn") so scripts/fetch_video_streams.py --aggregate
picks them up.

Usage:
    python3 scripts/probe_video_cdn.py [--workers 16] [--ids a,b,c] [--aggregate]
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
BASE = "https://jwbn3t9o8d.tenbytecdn.com/videos/{id}/"
UA = "Mozilla/5.0 (X11; Linux x86_64) LMCQ-recovery/1.0"

# rendition -> (quality, width, height)
REND = {
    "360p": ("sd", 640, 360),
    "540p": ("sd", 960, 540),
    "720p": ("hd", 1280, 720),
}

_lock = threading.Lock()


def log(*a):
    with _lock:
        print(*a, flush=True)


def video_ids():
    ids = {}
    for f in sorted(glob.glob(os.path.join(CATALOG, "video_*.json"))):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        ser = os.path.basename(f)[len("video_"):-len(".json")]
        for v in d.get("videos", []):
            vid = str(v.get("id") or "").strip()
            if vid:
                ids.setdefault(vid, set()).add(ser)
    return ids


def head(url, tries=3):
    """-> (content_length, last_modified) or (None, http_status)"""
    req = urllib.request.Request(url, method="HEAD",
                                headers={"User-Agent": UA})
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                cl = r.headers.get("Content-Length")
                return (int(cl) if cl else None, r.headers.get("Last-Modified"))
        except urllib.error.HTTPError as e:
            last = e.code
            if e.code in (403, 404, 400):
                break
            time.sleep(1 + n)
        except Exception:
            last = "err"
            time.sleep(1 + n)
    return (None, last)


def probe(vid):
    base = BASE.format(id=vid)
    lst = []
    for rend in ("720p", "540p", "360p"):
        size, lm = head(base + "%s_%s.mp4" % (vid, rend))
        if size:
            q, w, h = REND[rend]
            lst.append({
                "quality": q, "rendition": rend, "type": "video/mp4",
                "width": w, "height": h, "public_name": rend, "size": size,
                "link": "%s_%s.mp4" % (vid, rend), "last_modified": lm,
            })
    return {"video_id": vid, "video_base_url": base, "list": lst,
            "source": "cdn", "_id": vid}


def valid(p):
    try:
        d = json.load(open(p))
    except Exception:
        return False
    return bool(d.get("list")) and bool(d.get("video_base_url"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--ids", default="")
    ap.add_argument("--aggregate", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    ids = {i.strip(): set() for i in args.ids.split(",") if i.strip()} if args.ids else video_ids()

    todo = [v for v in ids if not valid(os.path.join(OUT, v + ".json"))]
    if args.limit:
        todo = todo[:args.limit]
    log("catalog: %d ids, todo: %d" % (len(ids), len(todo)))

    ok = miss = 0
    missing = []
    t0 = time.time()

    def work(vid):
        d = probe(vid)
        if d["list"]:
            tmp = os.path.join(OUT, vid + ".json.tmp")
            json.dump(d, open(tmp, "w"), ensure_ascii=False)
            os.replace(tmp, os.path.join(OUT, vid + ".json"))
        return d

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, v): v for v in todo}
        for i, f in enumerate(as_completed(futs), 1):
            v = futs[f]
            try:
                d = f.result()
                if d["list"]:
                    ok += 1
                    gb = sum(r["size"] for r in d["list"]) / 1e9
                    log("[%d/%d] %s  %d renditions  %.2f GB" % (i, len(todo), v, len(d["list"]), gb))
                else:
                    miss += 1
                    missing.append(v)
                    log("[%d/%d] %s  none on CDN" % (i, len(todo), v))
            except Exception as e:
                miss += 1
                missing.append(v)
                log("[%d/%d] %s  ERR %s" % (i, len(todo), v, e))

    log("done: found=%d missing=%d in %.1fs" % (ok, miss, time.time() - t0))
    if missing:
        p = os.path.join(OUT, "_missing.txt")
        open(p, "w").write("\n".join(missing) + "\n")
        log("missing -> %s (%d ids)" % (p, len(missing)))

    if args.aggregate:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import fetch_video_streams as fvs
        fvs.aggregate()


if __name__ == "__main__":
    main()
