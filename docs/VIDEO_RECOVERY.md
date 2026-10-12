# Video stream recovery

_Recovered 12 October 2026 · authorization LMCQ-DR-2026-1006_

## TL;DR

The lecture videos are **not** encrypted, **not** token-signed, and **not** tied to
the per-video `secret_key` in the app's data. They are plain progressive MP4
files on a public CDN, and the URL is a pure function of the numeric video id:

```
https://jwbn3t9o8d.tenbytecdn.com/videos/<id>/<id>_<rendition>.mp4
rendition ∈ {360p, 540p, 720p}
```

`GET`/`HEAD`/`Range` all work with **no auth header, no cookie, no `Referer`,
no signature, no expiry**. `media/videos/` is just not part of the recovered
tree, which is why the app looked like it "held" the videos.

The `secret_key` (`d83d332f82236a5fdafc80b598310b6f`) that appears on every
video record is a single static, app-level constant — it is not a per-video key
and it is not used in the CDN path. The `video-master/v2/api/` string in
`libapp.so` is a red herring: the real endpoint lives on the ordinary API.

## Evidence

`api_data/endpoints/` and the Dart snapshot of the APK
(`extracted/apk_x86/lib/x86_64/libapp.so`, strings: `get-video-list/`,
`get-video-resulation/`, `.m3u8`, `media_kit`, `hls1.4.10.js`) pointed at the
video API. The endpoint is reachable with the **normal** API token:

```bash
TOK=<api token>            # the same token scripts/fetch_exam_map.sh uses
curl -s "https://livemcq.com/api/v1/get-video-resulation/1758037080/" \
     -H "Authorization: Token $TOK"
```

```json
{
  "video_id": "1758037080",
  "video_base_url": "https://jwbn3t9o8d.tenbytecdn.com/videos/1758037080/",
  "list": [
    {"quality":"hd","rendition":"720p","type":"video/mp4","width":1280,"height":720,
     "size":1947655446,"size_short":"1.81 GB","link":"1758037080_720p.mp4"},
    {"quality":"sd","rendition":"540p","size":581490294,"link":"1758037080_540p.mp4"},
    {"quality":"sd","rendition":"360p","size":340756435,"link":"1758037080_360p.mp4"}
  ]
}
```

The `link` is appended to `video_base_url`. Fetching it directly:

```
HTTP/2 200
content-type: video/mp4
content-length: 340756435
server: TenbyteCDN-DAC1-0001
access-control-allow-origin: *
```

A ranged `GET` returns `206` and a real MP4 header
(`00 00 00 20 66 74 79 70 69 73 6f 6d … ftypisom / iso2 / avc1`), `ffprobe`
identifies it as `mov,mp4,m4a,3gp,3g2,mj2`. Directory listing of the CDN is
`403`, so filenames must be constructed — which is exactly what the pattern
above does.

Observed across the full inventory: **100% of verified videos use this single
CDN host and the same three renditions.** A few older ids have only 2 renditions.

## Notes / caveats

* The API (`get-video-resulation`) is nginx-rate-limited: ~190 requests at 8
  workers earned a blanket `403`. Go slow (≤1–2 req/s) or skip the API entirely
  and draft URLs from the catalogue — the CDN is the source of truth.
* The CDN itself is **flaky**: it intermittently drops connections (`curl` code
  `000`, HTTP/2 stream resets). Retries are mandatory; `aria2c --max-tries=8`
  handles it. Throughput when healthy is ~10 MB/s.
* Full-size rendering requires `Authorization: Token`, so this is only
  reproducible with a valid account token.

## Inventory

| | |
|---|---|
| videos | 2,177 |
| series | 73 |
| URLs (3 renditions each) | 6,531 |
| CDN host | `jwbn3t9o8d.tenbytecdn.com` |
| est. total, 720p only | ≈ 940 GB |
| est. total, 540p only | ≈ 428 GB |
| est. total, 360p only | ≈ 276 GB |
| est. total, all renditions | ≈ 1.6 TB |

Estimates are scaled from the sizes returned for the verified sample.

## Scripts

```bash
# 1. full URL inventory from the catalogue (offline, instant)
python3 scripts/make_video_urls.py
#    -> api_data/video_streams.json          id -> {base, series[], renditions[]}
#    -> viewer/data/video_streams.json       consumed by the viewer
#    -> api_data/video_urls_{360,540,720}p.txt

# 2a. optional: authoritative rendition lists + real sizes (rate-limited, slow)
LMCQ_TOKEN=<token> python3 scripts/fetch_video_streams.py --workers 2 --aggregate

# 2b. optional: verify/size directly against the CDN (no API, no auth)
python3 scripts/probe_video_cdn.py --workers 6 --aggregate

# 3. actually download
./scripts/download_videos.sh 360p --jobs 8
#    -> media/videos/<id>/<id>_<rendition>.mp4
```

`download_videos.sh` is resumable, keeps partial files, and writes into
`media/videos/`, which the viewer auto-detects.

## Viewer behaviour

`viewer/app.js` loads `data/video_streams.json` into `STREAMS` and every video
row now renders a play chip per rendition:

* click ▶ → opens the in-page `<video>` modal;
* the modal prefers a **local** copy at `media/videos/<id>/<file>` when it
  exists (probed with `HEAD`), otherwise streams the CDN URL;
* `↗` opens the resolved URL in a new tab / external app (the Android wrapper
  routes non-loopback navigations to the system browser so a tap can't replace
  the viewer).

The previous placeholder text ("Video streams are stored app-side (secret key)
— not recoverable") has been removed.
