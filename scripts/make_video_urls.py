#!/usr/bin/env python3
"""Build the full LiveMCQ video URL inventory (offline, no network needed).

The stream URL is a pure function of the numeric video id:

    https://jwbn3t9o8d.tenbytecdn.com/videos/<id>/<id>_<rendition>.mp4
    rendition in {360p, 540p, 720p}

so the complete inventory can be generated from the catalog alone. Where a
per-video JSON exists (api_data/video_streams/<id>.json, from the API or from
scripts/probe_video_cdn.py) its real size/rendition list is merged in.

Outputs
    api_data/video_streams.json         id -> {base, series[], renditions[]}
    viewer/data/video_streams.json      same, consumed by the offline viewer
    api_data/video_urls_<rend>.txt      one absolute URL per line (for aria2c)

Usage:  python3 scripts/make_video_urls.py [--base https://host/videos/]
"""
import argparse
import glob
import json
import os
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "api_data", "video_catalog")
PER_ID = os.path.join(ROOT, "api_data", "video_streams")
DEFAULT_BASE = "https://jwbn3t9o8d.tenbytecdn.com/videos/"
REND = ("720p", "540p", "360p")


def catalog_ids():
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    args = ap.parse_args()

    ids = catalog_ids()
    out = {}
    n_known = 0
    size_known = 0

    for vid, series in ids.items():
        base = args.base + vid + "/"
        rends = {}
        p = os.path.join(PER_ID, vid + ".json")
        if os.path.exists(p):
            try:
                d = json.load(open(p))
            except Exception:
                d = {}
            if d.get("video_base_url"):
                base = d["video_base_url"]
                for r in d.get("list", []):
                    rends[r.get("rendition")] = r
                n_known += 1
        lst = []
        for rend in REND:
            r = rends.get(rend)
            link = (r or {}).get("link") or ("%s_%s.mp4" % (vid, rend))
            size = (r or {}).get("size")
            if size:
                size_known += size
            lst.append({
                "rendition": rend,
                "quality": (r or {}).get("quality") or ("hd" if rend == "720p" else "sd"),
                "url": base + link,
                "file": link,
                "size": size,
                "w": (r or {}).get("width"),
                "h": (r or {}).get("height"),
                "verified": bool(r),
            })
        out[vid] = {"base": base, "series": sorted(series), "renditions": lst}

    dst1 = os.path.join(ROOT, "api_data", "video_streams.json")
    dst2 = os.path.join(ROOT, "viewer", "data", "video_streams.json")
    blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    open(dst1, "w").write(blob)
    open(dst2, "w").write(blob)

    # plain URL lists for aria2c / curl
    for rend in REND:
        urls = [r["url"] for v in out.values() for r in v["renditions"] if r["rendition"] == rend]
        open(os.path.join(ROOT, "api_data", "video_urls_%s.txt" % rend), "w").write("\n".join(urls) + "\n")

    hosts = sorted({urlparse(v["base"]).netloc for v in out.values()})
    total = sum(len(v["renditions"]) for v in out.values())
    print("videos:            %d" % len(out))
    print("series:            %d" % len({s for v in out.values() for s in v['series']}))
    print("URLs generated:    %d  (%d per video)" % (total, len(REND)))
    print("sizes known for:   %d videos  (%.2f GB of verified content)" % (n_known, size_known / 1e9))
    print("cdn host(s):       %s" % ", ".join(hosts))
    print()
    print("-> %s" % dst1)
    print("-> %s" % dst2)
    for rend in REND:
        print("-> api_data/video_urls_%s.txt" % rend)

    # rough projection for the unverified remainder
    if n_known:
        per = {r: 0 for r in REND}
        for v in out.values():
            for r in v["renditions"]:
                if r["size"]:
                    per[r["rendition"]] += r["size"]
        print()
        print("estimated totals for all %d videos (scaled from the %d verified):" % (len(out), n_known))
        for rend in REND:
            est = per[rend] / n_known * len(out)
            print("  %-5s %8.1f GB" % (rend, est / 1e9))


if __name__ == "__main__":
    main()
