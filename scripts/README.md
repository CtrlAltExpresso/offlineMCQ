# Scripts — LiveMCQ recovery

Every script is read-only against already-saved data, or writes new derived files.
None of them modify existing dump files.

| Script | Purpose | Output |
|---|---|---|
| `dump_api.sh` / `dump_api_v2.sh` | Original dump drivers for the exam lists + one-shot endpoints (v1 had a rate-limit bug; v2 is the fixed, resume-aware version) | `api_data/pages/`, `one_shot/`, `responses{,2}/` |
| `dump_pages_v2.sh` / `dump_pages_v3.sh` | Independent archive+routine list passes (for multi-pass verification) | `api_data/pages_v2/`, `pages_v3/` |
| `dump_questions.sh` | Master question bank, pages 1–1604 | `api_data/questions/page_*.json` |
| `dump_exammap.sh` | Orchestrates per-exam mapping with 3 parallel workers | `api_data/exam_maps/exam_<id>.json` |
| `fetch_exam_map.sh` | One exam: `exam-view` → payment-gate fallback `archive-question-subject`; atomic+validated write | one `exam_maps/` file or `error_<id>` marker |
| `scan_endpoints.sh` | Endpoint discovery sweep (polite pacing) | `api_data/endpoint_report*.tsv`, `responses3/` |
| `build_courses.py` | Rebuilds the 115 course files from canonical lists | `api_data/courses/*.json` |
| `build_sqlite.py` | Folds all dumps into one SQLite DB mirroring the app's Isar model (+FTS5) and emits the viewer's compact JSON shards | `viewer/livemcq.db`, `viewer/data/` |
| `build_media_list.py` | Collects every unique media URL referenced by saved content (3 hosts) | `api_data/media_download_list.tsv` |
| `download_media.py` | Resume-aware media fetcher (sha-verified, safe filenames) | `media/` |
| `build_media_manifest.py` | Disk-truth manifest (re-hashes every downloaded file) | `api_data/media_manifest.tsv` |
| `dump_video_catalog.sh` | Video series + class catalog from the videoseries endpoints | `api_data/video_catalog/` |
| `verify_lists.py` | Cross-checks dump passes (alignment, duplicates, union totals) | console report |
| `audit.py` | sha256 + record-count manifest for every file | `api_data/MANIFEST.tsv`, `INDEX.md` |
| `query.py` | Read-only CLI over `viewer/livemcq.db` (stats, exam lookup, exam question dumps, per-qid detail, FTS search, audio stats) — see the Usage block at its top | console |
| `make_content_bundle.py` | Zips the viewer + media tree (already on disk) into 22 indexless zip parts + a manifest for the Android offline app | a bundle dir (`part_*.zip` + `livemcq_manifest.json`) |

## Resume-after-power-loss

All dump scripts are idempotent: a file that exists and passes validation is skipped.
A partially-written file never counts. Rerunning the script resumes where it stopped.