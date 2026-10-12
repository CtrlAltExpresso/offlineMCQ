#!/usr/bin/env bash
# Download LiveMCQ lecture videos from the (unauthenticated) CDN.
#
#   ./scripts/download_videos.sh 360p                 # smallest, ~all of it is big
#   ./scripts/download_videos.sh 540p --jobs 6
#   ./scripts/download_videos.sh 360p --ids 1758037080,1789895687
#   ./scripts/download_videos.sh 720p --dry-run
#
# Files land in media/videos/<id>/<id>_<rendition>.mp4, which the offline viewer
# auto-detects and plays from local disk (it falls back to streaming the CDN URL
# when the file is absent).
#
# aria2c gives us parallel connections, resume, and automatic retry. Install:
#   Arch/BlackArch : pacman -S aria2
#   Debian/Ubuntu  : apt install aria2
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REND="${1:-360p}"; shift || true
JOBS=8
OUTDIR="$ROOT/media/videos"
IDS=""
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --jobs) JOBS="$2"; shift 2;;
    --ids)  IDS="$2"; shift 2;;
    --out)  OUTDIR="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

JSON="$ROOT/api_data/video_streams.json"
[ -s "$JSON" ] || { echo "missing $JSON — run: python3 scripts/make_video_urls.py" >&2; exit 1; }

command -v aria2c >/dev/null || { echo "aria2c not found (pacman -S aria2 / apt install aria2)" >&2; exit 1; }

mkdir -p "$OUTDIR"
LIST="$(mktemp /tmp/opencode/aria_in.XXXXXX)"
trap 'rm -f "$LIST"' EXIT

python3 - "$JSON" "$REND" "$LIST" "$IDS" <<'PY'
import json, sys, os
j, rend, listpath, ids = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
d = json.load(open(j))
want = set(x.strip() for x in ids.split(",") if x.strip()) if ids else None
n = 0
with open(listpath, "w") as fh:
    for vid, v in d.items():
        if want and vid not in want: continue
        for r in v["renditions"]:
            if r["rendition"] != rend: continue
            # aria2c "url <TAB> out=..." so each file gets its own directory
            fh.write("%s\n  out=%s\n  dir=%s\n" % (r["url"], r["file"], "videos/" + vid))
            n += 1
print("queued %d URLs (%s)" % (n, rend), file=sys.stderr)
PY

cd "$ROOT/media"
if [ "$DRY" = "1" ]; then
  echo "--- dry run, input list ---"; head -20 "$LIST"; echo "..."; exit 0
fi

aria2c \
  --input-file="$LIST" \
  --continue=true \
  --max-concurrent-downloads="$JOBS" \
  --max-connection-per-server=4 \
  --split=4 \
  --min-split-size=8M \
  --max-tries=8 \
  --retry-wait=5 \
  --timeout=30 \
  --connect-timeout=15 \
  --auto-file-renaming=false \
  --allow-overwrite=false \
  --file-allocation=none \
  --summary-interval=30 \
  --console-log-level=warn \
  --download-result=hide \
  --user-agent="Mozilla/5.0 (X11; Linux x86_64) LMCQ-recovery/1.0"

echo
echo "done -> $ROOT/media/videos/"
du -sh "$ROOT/media/videos" 2>/dev/null || true
