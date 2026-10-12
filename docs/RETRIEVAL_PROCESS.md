# LiveMCQ Data Recovery — Retrieval Process

Full write-up of how the content was recovered, so any step can be reproduced or audited.

---

## 0. Authorization

- **Who:** Nabil Rahman (owner, `nabilrahman@livemcq.com`, `+880 1935452344`)
- **Ref:** `LMCQ-DR-2026-1006`, signed 2026-10-06, valid through 2026-12-31
- **Document:** [`LiveMCQ_Data_Recovery_Authorization.pdf`](../LiveMCQ_Data_Recovery_Authorization.pdf) · [`.txt`](../LiveMCQ_Data_Recovery_Authorization.txt)
- Authorization letter covers the APK, on-device app data, the live API, and the backend
  infrastructure.

## 1. App extraction (Step 1)

A copy of the app environment ran inside Waydroid (x86_64). Pulled from the running session:

| Artifact | Size | Notes |
|---|---|---|
| `base.apk` | 84.8 MB | main APK |
| `split_config.x86_64.apk` | 81.9 MB | contains `libapp.so` (AOT-compiled Flutter), `libisar.so`, `libsqlcipher.so` |
| `/data/data/com.livemcq.livemcq` | ~1 MB DB | Isar DB (7 collections), GetStorage, Flutter shared prefs (secure storage is device-bound and unrecoverable) |
| JADX decompile | — | Java/Kotlin/native layer — Flutter Dart source is AOT-compiled and not recoverable from the APK |

Full inventory in [`STEP1_EXTRACTION_REPORT.md`](STEP1_EXTRACTION_REPORT.md).

The single most useful find: **a JWT-derived API token** inside GetStorage, which unlocked the
API (see §2).

## 2. API discovery

- **Base URL:** `https://livemcq.com/api/v1`
- **Auth:** `Authorization: Token <hex>`, scheme "Token" (not "Bearer").
- Endpoint names were mined from `libapp.so` string table (61,776 strings → 82 candidates →
  734 route strings → curated 191 scan targets).
- Discovery method: polite HTTP scans (≤1.2 s between requests; the server enforces an nginx
  `limit_req` of ~5–6 req/s → HTTP 403, clearing in ~45–90 s).

**Key finding — questions live behind a stable paginated feed:**

```
GET question-by-tag/1/?page=N     → 50 questions/page, 1,604 pages, 80,162 total
```

`tag_id` is ignored by the server (any value returns the same global feed).

## 3. The dumps

### 3.1 Exam lists (archive + routine)

| Endpoint | Pages | Rows |
|---|---|---|
| `question/new_get_central_archive` | 774 | 15,469 rows |
| `question/new_get_central_routine` | 63 | 1,248 rows |

**Known quirk:** the API's row count ≠ distinct exam count. The list query walks an unstable
(joins + non-unique ORDER BY) row set, so:

- single pass returns `distinct + ~40 duplicated rows`,
- the same exam can straddle two adjacent pages between passes.

**Resolution:** 3 independent full passes were dumped (`pages/`, `pages_v2/`, `pages_v3/`),
then union-verified. Capture–recapture estimate (N̂ = |A||B|/|A∩B|) predicted 15,428; pass 3
added 1 record → **15,429 distinct archive exams**, written to
`exam_list_canonical.jsonl`. Cross-pass content disagreement was 4/15,429 records (user
attendance flags changing), resolved newest-pass-wins.

### 3.2 Question bank

`question-by-tag/1/?page=N` for N = 1..1604 → 80,162 unique questions (each with question
text, 4–5 options, `answer`, `explain` HTML, `slug`).

Verified: file↔`pagination.current_page` alignment 1604/1604 ✓, zero duplicate IDs ✓,
merged JSONL id-set == page id-set ✓, content equality on a 500-ID random sample ✓.

**Note on the bank size:** the API reports 1,604 × 50 pages but the last page holds 12,
giving exactly 80,162 (not 80,200).

### 3.3 Legacy exam content (per-exam maps)

`exam-view/<id>` returns one exam's questions grouped by subject. **Viewing is
payment-gated** for some exams (`{"ERROR": "Payment not Valid"}` → ~20% of the older set).

**Fallback confirmed same-content:** `archive-question-subject/<id>` returns the same
questions without the payment check. Verified by:
1. byte-identical question/answer/option match on non-gated exams,
2. every fallback file matching its course-declared question count (262/263 during
   development; the 1 exception was stale *metadata* — both endpoints agree at 40).

Every map is written atomically (`*.tmp` → rename), validated on read, and only fully-valid
files count. Resumable after any interruption (e.g., power loss).

**Result (completed):** 16,692 attempts → **16,167 exam maps** (788,466 question
instances), **525 permanent NO_CONTENT** (both endpoints return 200 with an empty
question set — payment-locked at DB level, same as an app non-owner view), plus a few
dozen transient 403 retries that succeeded on re-run. Final: 0 transient errors, 0
missing, 0 extras vs the canonical lists.

## 4. Endpoint inventory

Every reachable endpoint, status, and allowed method is tabulated in
[`API_ENDPOINTS.md`](API_ENDPOINTS.md) (generated from the scan reports in `api_data/`).

## 5. Course reconstruction

Given exam records carry `subject_id` + `subject_name`, the app's on-screen structure was
rebuilt from the canonical lists into 115 course files (`api_data/courses/`), each listing
its exams with pointers (under `files[]`) to the per-exam maps.

## 6. Integrity & backups

- **`MANIFEST.tsv`** — sha256 + record counts for every file (regenerated by
  `scripts/audit.py`).
- **G**it is the off-machine backup via a private GitHub repo; big derived artifacts are
  chunked to GitHub's 100 MB/file limit.
- Media files (PDF/images/videos) remain queued (see §Status in the README).