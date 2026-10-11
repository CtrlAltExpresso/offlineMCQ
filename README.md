<div align="center">

# 📲 offlineMCQ

**The LiveMCQ exam app — every exam, every question, fully on your phone.**
**No internet needed after setup. Free. No account. No ads.**

<br>

<a href="https://github.com/CtrlAltExpresso/offlineMCQ/releases/latest/download/offlineMCQ.apk">
  <img src="https://img.shields.io/badge/📥%20DOWNLOAD%20THE%20APP-Android%20APK-16a34a?style=for-the-badge&logo=android&logoColor=white" width="460" alt="DOWNLOAD THE APP — Android APK">
</a>

<br>
<br>

**⬇️ Download &nbsp;·&nbsp; 📂 Open file &nbsp;·&nbsp; ✅ Install &nbsp;·&nbsp; 🎉 Done**

*No Google Play · No login · No hidden fees*

</div>

---

## 📥 Install in 2 minutes

1. **Tap the green button above** — your phone downloads `offlineMCQ.apk` (only 33 KB).
   Direct link: **https://github.com/CtrlAltExpresso/offlineMCQ/releases/latest/download/offlineMCQ.apk**
2. **Open the downloaded file** (from your browser or file manager).
3. Tap **Install**. If Android asks, allow *"install unknown apps"* for your browser / file manager.
4. **Open offlineMCQ.** It automatically downloads all exams & questions once (**~9 GB — use Wi-Fi**), then works **100% offline — forever**.

> 💡 That's it. The app fetches its own content on first launch; you never download or move anything manually.

---

## ℹ️ What is this?

**offlineMCQ** is the complete content of the LiveMCQ Android app (Bangladeshi BCS / Bank /
Government-job MCQ test platform) — **15,429 archive exams** + **1,263 routine entries** +
**80,162 questions with answers & explanations**, organized as **115 courses → exams → questions**,
verified with checksums and cross-checked across independent dump passes.

[![Exams](https://img.shields.io/badge/exams-15%2C429%20%2B%201%2C263-16a34a?style=flat-square)](#-whats-inside)
[![Questions](https://img.shields.io/badge/questions-80%2C162-0f172a?style=flat-square)](#-whats-inside)
[![Courses](https://img.shields.io/badge/courses-115-3b82f6?style=flat-square)](#-course--exam--question)
[![Integrity](https://img.shields.io/badge/integrity-sha256%20verified-64748b?style=flat-square)](#-integrity)

The app was built behind a growing collection of exams and questions that were at risk of being
lost. With the app owner's authorization (see [`authorization/`](authorization/)), everything the
app serves was pulled from its live API and re-organized into a structure that mirrors what the
app shows:

## 🎯 What is this?

The LiveMCQ app (Bangladeshi BCS / Bank / Government-job MCQ test platform) was built behind a
growing collection of exams and questions that were at risk of being lost. With the app owner's
authorization (see [`authorization/`](authorization/)), everything the app serves was pulled
from its live API and re-organized into a structure that mirrors what the app shows:

```
app:   Course (subject)  →  Exam  →  Questions
repo:  courses/<name>.json → exam_maps/exam_<id>.json
```

This is a full job: every page, every exam, every question — nothing sampled, nothing skipped.
Paid/"payment-gated" exams are included too (fetched through the app's alternate endpoint).

## 📊 What's inside

| Asset | Count | Location |
|---|---|---|
| Courses (subjects) | 115 | [`api_data/courses/`](api_data/courses/) — one readable-named file each |
| Archive exams | 15,429 | [`api_data/exam_list_canonical.jsonl`](api_data/exam_list_canonical.jsonl) |
| Routine exams | 1,263 | [`api_data/routine_list_canonical.jsonl`](api_data/routine_list_canonical.jsonl) |
| Questions (master bank) | 80,162 | [`api_data/question_bank_chunks/`](api_data/question_bank_chunks/) |
| Per-exam question maps | 16,167 | [`api_data/exam_maps/`](api_data/exam_maps/) |
| App artifacts (APKs + original data) | — | [`extracted/`](extracted/) |
| Discovery/verification | — | [`docs/`](docs/), [`scripts/`](scripts/), `MANIFEST.tsv` |

## 🧭 Course → Exam → Question

All 115 courses are named files — [`api_data/courses/`](api_data/courses/). Example:

```
api_data/courses/১৪০_দিনে_৫২তম_বিসিএস_প্রস্তুতি.json
```

Each course file lists every exam in it (`exam_id`, date, question count). Click the exam's
`files` path to open `api_data/exam_maps/exam_<id>.json` — the full exam: every question,
its 4–5 options, the correct answer, and the explanation.

The master question bank is split into 3 line-safe JSONL chunks (each individually valid,
self-contained), because the merged file (106 MB) exceeds GitHub's 100 MB per-file limit:
`cat question_bank.aa question_bank.ab question_bank.ac > all_questions.jsonl`.

## 🔒 Integrity

- **`api_data/MANIFEST.tsv`** — sha256 + record count for every single dumped file (2,493 files)
- **`api_data/INDEX.md`** — human-readable inventory of the whole dump
- Exam lists were dumped **3 independent times** and union-verified — cross-pass agreement
  proved the set is complete (the API itself returns ~40 duplicate *rows* from an unstable
  join; true distinct count was established and canonicalized)
- Every exam map is validated (must parse as JSON with a non-empty question set) before it
  counts; corrupted/partial files are never kept

## 📂 Quick start

```bash
# browse courses (names in Bangla)
ls api_data/courses/

# open a course, see its exams
jq '.name, .exams_count' api_data/courses/ডেইলি_কুইজ_২০০_দিন.json

# read one exam's questions
jq '.question_text' api_data/exam_maps/exam_1.json | head -40

# reassemble the master question bank
cat api_data/question_bank_chunks/question_bank.* > /tmp/all_questions.jsonl

# verify a file against the manifest
cd api_data && sed -n '2p' MANIFEST.tsv
```

## ✨ Offline app clone + SQLite

Two browse-ready deliverables are generated from the dumps. Both are 100% local / offline.

### 1) Offline viewer — an exact-style clone of the app

`viewer/` is a tiny static PWA-free site that reproduces the LiveMCQ in-app experience
(brand navy + amber, the app's own `anekbangla` / `Montserrat` fonts pulled from the APK):
course cards → exam lists → full exam-taking (pick an option, see correct/wrong, read the
HTML explanation, get a score), question search, the video-class library and the study-PDF
library with in-app PDF preview.

```bash
python3 viewer/serve.py
# → open http://localhost:8000/viewer/
```

Everything it needs already ships in the repo: the compact shards under `viewer/data/`
(regenerate locally with the script below) and the per-exam JSON in `api_data/exam_maps/`.
Video thumbnails and PDF handouts load from `media/` (present on this machine).

### 2) SQLite database — mirrors the app's own Isar data model

`scripts/build_sqlite.py` folds every dataset into one file, `viewer/livemcq.db`
(≈1.9 GB), with tables that mirror the collections recovered from the app's own
`default.isar` schema, plus a contentless-FTS5 full-text index:

```
subject(id, name, slug_or_type)            ← exam subject cards
exam(id, subject_id, date, question_number, is_omr, slug, exam_time_ms,
     omr_time_ms, is_mapping, has_content, title)            ← IsarExamModel
question(qid, question, options_json, answer_index, answer_text,
         explanation_html, is_audio, q_duration_ms, a_duration_ms,
         e_duration_ms, slug, syllabus, source, has_bank)     ← IsarExamModel+bank
exam_question(exam_id, qid, position, subject_group)         ← questionSlugList
video_series(id, type, title) / video(video_id, series_id, title, thumbnail_url,
         pdf_url, secret_key, is_free, duration, class_date, created_at, sort_order)
                                                            ← IsarVideoModel
pdf(url, title, rel_path, size_bytes, sha256)  /  media_url(rel_path, …)
question_fts — FTS5 (contentless) + fts_doc(rowid → qid)     ← search
```

```bash
python3 scripts/build_sqlite.py     # (re)builds viewer/livemcq.db + viewer/data/*
sqlite3 viewer/livemcq.db "SELECT count(*) FROM question;"
sqlite3 viewer/livemcq.db \
  "SELECT q.question, q.answer_text FROM question_fts
   JOIN fts_doc ON fts_doc.rowid = question_fts.rowid
   JOIN question q ON q.qid = fts_doc.qid
   WHERE question_fts MATCH 'সঞ্চারপথ' ORDER BY rank LIMIT 5;"
```

`viewer/livemcq.db` and `viewer/data/` are regenerable build artifacts (gitignored);
the committed pieces are the generator script and the viewer sources.

**About the audio questions:** a **real** app feature the recovery left behind —
the API flags **271,834 questions** across **8,280 audio-pack exams** (`audio_all_list`),
and the app keeps them in an `IsarAudioModel(audioUrl)`. The audio *files* are served
from `bdix1.livemcq.com/audio-files/audios/<slug>` — a hostname with no public DNS —
and no audio URL appears in any saved API response or in the app's own database, so the
audio bytes are unrecoverable from the current access (the same class of limitation as
the video streams). The viewer simply doesn't surface the flag.

### 3) Android APK — the whole viewer on a phone, fully offline

`android/` (see [`android/README.md`](android/README.md)) builds a small sideloadable
APK (`offlineMCQ.apk`, 33 KB) that runs the viewer on a phone or tablet with
zero internet after setup. On first launch the app downloads the ~9 GB content bundle
itself — SHA-256-verified, HTTP-Range-resumable,
free-space-checked — then extracts and serves it from a loopback server to an embedded
WebView. The bundle (22 zip parts + `livemcq_manifest.json`, 8.76 GB uncompressed) is
produced by `scripts/make_content_bundle.py` and uploadable to archive.org or any
Range-capable host. A single >4 GB "all-in-one" APK was proven impossible (Android's APK
reader and Google's sign/align tools lack zip64; PDFs alone are 4.8 GB).

## 📦 Status

| Step | State |
|---|---|
| Authorization | ✅ 2026-10-06 (LMCQ-DR-2026-1006, valid through 2026-12-31) |
| App extraction (APK + original data) | ✅ |
| Exam lists (3-pass verified) | ✅ 15,429 + 1,263 |
| Question bank | ✅ 80,162 |
| Per-exam maps | ✅ 16,167 (525 exams are permanently empty/locked in the API) |
| Media (images / PDFs) | ✅ 35,206 files / 8.98 GB (`media/`, manifest committed) |
| Video catalog (75 series → 2,198 classes) | ✅ metadata + study PDFs; streams are player-side |
| **Offline viewer** (`viewer/`) | ✅ app-style clone: Home · Routine · Search · Classes · PDFs |
| **SQLite DB** (`viewer/livemcq.db`, ~1.9 GB) | ✅ mirrors Isar model + FTS5 search |
| **Android APK** (`android/` → `dist/LiveMCQ_Offline.apk`) | ✅ signed 33 KB; downloads the 8.76 GB bundle on first run |

**About the 525:** 16,692 `exam-view`/`archive-question-subject` fetches were attempted.
525 (3.1%) return an empty question set in the API itself (payment-locked at database
level) — the same view a non-owner account sees in the app. The remaining 16,167 all
fetch valid question sets. These 525 exams still appear in their course files
(`exam_maps` entry shows no `files`); a future owner-level account/server dump can
fill them in. All 525 are members of the routine list, and the viewer's **Routine** tab
shows the full 1,263-exam routine schedule — 297 with content, the rest marked Locked.

**About the media:** every unique asset URL referenced by the app's own content was
downloaded from the three hosts it uses (`elasticbeanstalk…s3.amazonaws.com`,
`assets.livemcq.com`, `files.livemcq.app`): **35,210 URLs → 35,206 files (8.98 GB)**.
Kinds: 32,600+ images (png/jpg/jpeg/webp/gif/avif/svg), 1,846 class/study PDFs and a
docx that live in `media/documents/`. Only 4 URLs are unrecoverable (3 removed from S3
→ HTTP 403; 1 is a URL truncated inside the app's own database → HTTP 400). The full
registry — `media_manifest.tsv` (url ⇄ sha256 ⇄ size ⇄ status) and
`media_download_list.tsv` (url ⇄ relpath) — is committed; the binary files themselves
are kept in `media/` (gitignored, ~9 GB) so the repo stays under GitHub's limits.

**About the videos:** `videoseries-subject-list` exposes **75 video-series subjects**;
`get-video-list/<subject_id>` returns their **2,198 class sessions** (title, date,
duration, free/paid, thumbnail, `pdf_link`, embed `secret_key`) — saved under
`api_data/video_catalog/video_<subject>.json`. Playback streams are served by the app's
own player keyed on `secret_key`, so video *bytes* aren't recoverable from the API, but
every class's full catalog + attached PDFs are.

## 🛠 Background

- **App package:** `com.livemcq.livemcq` (Flutter). Data pulled from `https://livemcq.com/api/v1`.
- **Full methodology:** see [`docs/RETRIEVAL_PROCESS.md`](docs/RETRIEVAL_PROCESS.md).
- **Raw endpoint inventory:** see [`docs/API_ENDPOINTS.md`](docs/API_ENDPOINTS.md).
- **Scripts (documented):** see [`scripts/README.md`](scripts/README.md).
- **Authorization:** [`authorization/LiveMCQ_Data_Recovery_Authorization.pdf`](authorization/LiveMCQ_Data_Recovery_Authorization.pdf)

---

<div align="center">

*Recovered with the explicit, signed authorization of the LiveMCQ app owner (Ref: LMCQ-DR-2026-1006).*

</div>