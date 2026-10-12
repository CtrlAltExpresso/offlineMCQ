#!/usr/bin/env python3
"""Build viewer/livemcq.db — the LiveMCQ content, mirrored to the app's own
data model (Isar collections: exam, question, video, media) plus an FTS5
search index. Pure local data; fully offline. Only content dumps are used.

Schema (mirrors the recovered app model):
  subject    (id, name, slug_or_type)          ~ IsarExamModel.subject grouping
  exam       (id, subject_id, date, question_number, is_omr, slug,
              exam_time_ms, omr_time_ms, is_mapping, has_content, title)
  question   (qid=md5(normalized text), question, options_json, answer_index,
              answer_text, explanation_html, is_audio, q_duration_ms,
              a_duration_ms, e_duration_ms, slug, syllabus, source)
  exam_question (exam_id, qid, position, subject_group)
  video_series (id, type, title)
  video      (video_id, series_id, title, thumbnail_url, pdf_url, secret_key,
              is_free, duration, class_date, created_at, sort_order)
  pdf        (url, title, rel_path, size_bytes, sha256)
  media_url  (rel_path, size_bytes, sha256, kind)
  question_fts (FTS5: qid, question, options, answer, explanation)
"""
import json, os, re, glob, sqlite3, hashlib, html, sys, time

ROOT = '/home/sakib/offlineMCQ'
API = f'{ROOT}/api_data'
OUT = f'{ROOT}/viewer/livemcq.db'
t0 = time.time()
if os.path.exists(OUT):
    os.remove(OUT)
db = sqlite3.connect(OUT)
db.execute('PRAGMA journal_mode=OFF')
db.execute('PRAGMA synchronous=OFF')

db.executescript('''
CREATE TABLE subject(id INTEGER PRIMARY KEY, name TEXT, slug_or_type TEXT);
CREATE TABLE exam(id INTEGER PRIMARY KEY, subject_id INTEGER, date TEXT,
  question_number INTEGER, is_omr INTEGER, slug TEXT,
  exam_time_ms INTEGER, omr_time_ms INTEGER, is_mapping INTEGER,
  has_content INTEGER, title TEXT);
CREATE TABLE question(qid TEXT PRIMARY KEY, question TEXT, options_json TEXT,
  answer_index INTEGER, answer_text TEXT, explanation_html TEXT,
  is_audio INTEGER, q_duration_ms INTEGER, a_duration_ms INTEGER,
  e_duration_ms INTEGER, slug TEXT, syllabus TEXT, source TEXT, has_bank INTEGER);
CREATE TABLE exam_question(exam_id INTEGER, qid TEXT, position INTEGER,
  subject_group TEXT);
CREATE TABLE video_series(id INTEGER PRIMARY KEY, type TEXT, title TEXT);
CREATE TABLE video(video_id INTEGER PRIMARY KEY, series_id INTEGER, title TEXT,
  thumbnail_url TEXT, pdf_url TEXT, secret_key TEXT, is_free INTEGER,
  duration TEXT, class_date TEXT, created_at TEXT, sort_order INTEGER);
CREATE TABLE pdf(url TEXT PRIMARY KEY, title TEXT, rel_path TEXT,
  size_bytes INTEGER, sha256 TEXT);
CREATE TABLE media_url(rel_path TEXT PRIMARY KEY, size_bytes INTEGER,
  sha256 TEXT, kind TEXT);
-- contentless FTS: stores only the index, not the text. Query with
--   SELECT rowid, rank FROM question_fts WHERE question_fts MATCH ?
--   JOIN fts_doc ON fts_doc.rowid = question_fts.rowid JOIN question ON question.qid = fts_doc.qid
CREATE VIRTUAL TABLE question_fts USING fts5(qid UNINDEXED, question,
  options, answer, explanation, content='', tokenize='unicode61');
CREATE TABLE fts_doc(rowid INTEGER PRIMARY KEY, qid TEXT);
CREATE INDEX idx_eq_exam ON exam_question(exam_id);
CREATE INDEX idx_eq_qid  ON exam_question(qid);
CREATE INDEX idx_exam_subj ON exam(subject_id);
CREATE INDEX idx_vid_series ON video(series_id);
''')

_PREFIX = re.compile(r'^\s*[0-9০-৯]{1,6}\s*[\.।)]\s*')
def norm(s):
    if not s:
        return ''
    s = s.replace('\u00a0', ' ').replace('\u200d', '').strip()
    s = _PREFIX.sub('', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

# ---------------- subjects ----------------
subjects = {}      # id -> (name, slug)
n_s = 0
course_files = []
for f in glob.glob(f'{API}/courses/*.json'):
    if os.path.basename(f) == 'courses.json':
        continue
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if not isinstance(d, dict) or d.get('subject_id') is None:
        continue
    course_files.append(f)
    sid = d.get('subject_id')
    subjects[sid] = (d.get('name') or '', d.get('slug_or_type') or '')
    n_s += 1
print(f'subjects: {n_s}')

# ---- per-exam name source: canonical lists carry syllabus/subject_name ----
exam_info = {}   # exam_id -> dict (syllabus, subject_name, type)
for _f in (f'{API}/exam_list_canonical.jsonl', f'{API}/routine_list_canonical.jsonl'):
    if not os.path.exists(_f):
        continue
    with open(_f, encoding='utf-8') as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if isinstance(d, dict) and d.get('id') is not None:
                exam_info[d['id']] = d
print(f'canonical list info: {len(exam_info)} exams')

# ---------------- exams ----------------
exams = {}        # id -> dict
n_e = 0
for sid, (name, slug) in subjects.items():
    for cfile in course_files:
        d = json.load(open(cfile))
        if d.get('subject_id') != sid:
            continue
        for ex in d.get('exams', []):
            eid = ex.get('exam_id')
            if eid is None:
                continue
            exams[eid] = dict(subject_id=sid,
                              date=ex.get('date') or '',
                              question_number=ex.get('question_number') or 0,
                              is_omr=1 if str(ex.get('is_omr')).lower() in ('true', '1') else 0,
                              slug=ex.get('slug') or '')
            n_e += 1
print(f'exams from subjects: {n_e}')
# merge per-exam metadata (timers, omr, mapping, content flag)
for f in glob.glob(f'{API}/exam_maps/exam_*.json'):
    m = re.match(r'^exam_(\d+)\.json$', os.path.basename(f))
    if not m:
        continue
    eid = int(m.group(1))
    d = exams.setdefault(eid, dict(subject_id=None, date='', question_number=0,
                                   is_omr=0, slug=''))
    try:
        raw = json.load(open(f))
    except Exception:
        continue
    d['has_content'] = 1
    d['exam_time_ms'] = raw.get('exam_time')
    d['omr_time_ms'] = raw.get('omr_time')
    d['is_mapping'] = 1 if str(raw.get('is_mapping')).lower() in ('true', '1') else 0
    d['is_omr'] = 1 if str(raw.get('is_omr')).lower() in ('true', '1') else d.get('is_omr', 0)
    if raw.get('examname'):
        d['title'] = raw['examname']
    if raw.get('syllabus') and not d.get('title'):
        d['title'] = raw['syllabus']
print(f'exams total: {len(exams)}')

# ---- exam titles: only this exam's own API fields, never invented ----
# order of trust: exam_map.examname > exam_map.syllabus > canonical.syllabus
for eid, d in exams.items():
    if d.get('title'):
        continue
    info = exam_info.get(eid)
    if info:
        syl = (info.get('syllabus') or '').strip()
        if syl:
            d['title'] = re.sub(r'\s+', ' ', syl).strip()
        else:
            d['title'] = ''
    else:
        d['title'] = ''

# ---------------- questions (union of exam maps + bank) ----------------
qrows = {}        # norm -> dict
n_q = 0
n_i = 0
def add_question(src, d, bank=False):
    global n_q, n_i
    qtext = d.get('question') or ''
    k = norm(qtext)
    if not k:
        return None
    existing = qrows.get(k)
    opts = [d.get(f'option{i}') or '' for i in range(1, 6)]
    if bank:
        a = int(d.get('answer') or 0)
        atext = opts[a - 1] if 1 <= a <= len(opts) else ''
        row = dict(qid='', question=qtext, options_json=json.dumps(opts),
                   answer_index=a, answer_text=atext,
                   explanation_html=d.get('explain') or d.get('explanation') or '',
                   is_audio=0, q_duration=None, a_duration=None, e_duration=None,
                   slug=d.get('slug') or '', syllabus=d.get('syllabus') or '',
                   source='bank', has_bank=1)
    else:
        a = int(d.get('answer') or 0)
        atext = opts[a - 1] if 1 <= a <= len(opts) else ''
        exp = d.get('exp') or d.get('explanation') or d.get('explain') or ''
        row = dict(qid='', question=qtext, options_json=json.dumps(opts),
                   answer_index=a, answer_text=atext, explanation_html=exp,
                   is_audio=1 if str(d.get('is_audio')).lower() in ('true', '1') else 0,
                   q_duration=d.get('question_duration'), a_duration=d.get('answer_duration'),
                   e_duration=d.get('explain_duration'), slug=d.get('slug') or '',
                   syllabus=d.get('syllabus') or '', source='exam', has_bank=0)
    if existing is None:
        row['qid'] = hashlib.md5(k.encode()).hexdigest()[:16]
        qrows[k] = row
        n_q += 1
    else:
        # sysnthesis: keep better of both
        if bank and existing.get('source') == 'exam':
            merge = {'explanation_html': existing['explanation_html'] or (row['explanation_html'] or ''),
                     'is_audio': existing['is_audio'] or row['is_audio'],
                     'q_duration': existing['q_duration'] or row['q_duration'],
                     'a_duration': existing['a_duration'] or row['a_duration'],
                     'e_duration': existing['e_duration'] or row['e_duration'],
                     'answer_text': row['answer_text'] or existing['answer_text'],
                     'answer_index': row['answer_index'] or existing['answer_index'],
                     'slug': row['slug'] or existing['slug'],
                     'syllabus': row['syllabus'] or existing['syllabus'],
                     'options_json': existing['options_json']}
            for kk in ('explanation_html', 'is_audio', 'q_duration', 'a_duration', 'e_duration',
                       'answer_text', 'answer_index', 'slug', 'syllabus', 'options_json'):
                existing[kk] = merge[kk]
            existing['has_bank'] = 1
            existing['source'] = 'both'
    n_i += 1
    return qrows[k]

# pass 1: exam maps (order preserved)
eq_rows = []      # (exam_id, qid, position, group)
map_files = [f for f in glob.glob(f'{API}/exam_maps/exam_*.json')
             if re.match(r'^exam_\d+\.json$', os.path.basename(f))]
for idx, f in enumerate(map_files):
    eid = int(os.path.basename(f)[5:-5])
    try:
        raw = json.load(open(f))
    except Exception:
        continue
    pos = 0
    qt = raw.get('question_text') or {}
    for group, qs in qt.items():
        if not isinstance(qs, list):
            continue
        for q in qs:
            if not isinstance(q, dict):
                continue
            r = add_question('exam', q)
            if r:
                pos += 1
                eq_rows.append((eid, r['qid'], pos, group))
    if (idx + 1) % 3000 == 0:
        print(f'  maps {idx+1}/{len(map_files)}  questions {n_q}  instances {n_i}', flush=True)
print(f'exam-maps pass: questions={n_q} instances={n_i}')

# pass 2: global bank
if os.path.exists(f'{API}/all_questions.jsonl'):
    with open(f'{API}/all_questions.jsonl', encoding='utf-8') as fh:
        for i, line in enumerate(fh):
            if i == 0 and line.startswith('{'):
                pass
            try:
                q = json.loads(line)
            except Exception:
                continue
            add_question('bank', q, bank=True)
    print(f'bank pass: questions total={n_q}')
else:
    print('all_questions.jsonl missing; bank pass skipped')

db.executemany('INSERT INTO subject VALUES (?,?,?)',
               [(sid, name, slugs) for sid, (name, slugs) in subjects.items()])
db.executemany('INSERT INTO exam VALUES (?,?,?,?,?,?,?,?,?,?,?)',
               [(eid, d.get('subject_id'), d.get('date'), d.get('question_number'),
                 d.get('is_omr', 0), d.get('slug', ''), d.get('exam_time_ms'),
                 d.get('omr_time_ms'), d.get('is_mapping', 0),
                 1 if d.get('has_content') else 0, d.get('title'))
                for eid, d in sorted(exams.items())])
db.executemany('INSERT INTO question VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               [(r['qid'], r['question'], r['options_json'], r['answer_index'],
                 r['answer_text'], r['explanation_html'], r['is_audio'],
                 r['q_duration'], r['a_duration'], r['e_duration'], r['slug'],
                 r['syllabus'], r['source'], r.get('has_bank', 0))
                for r in qrows.values()])
db.executemany('INSERT INTO exam_question VALUES (?,?,?,?)', eq_rows)
print(f'inserted questions={len(qrows)} exam_question={len(eq_rows)}')
# FTS (in chunks)
print('building FTS index...', flush=True)
chunk = []
ftsd = []
for r in qrows.values():
    opts = ' '.join(json.loads(r['options_json']))
    chunk.append((r['qid'], r['question'], opts, r['answer_text'],
                  r['explanation_html'] or ''))
    ftsd.append((r['qid'],))
    if len(chunk) >= 20000:
        db.executemany("INSERT INTO question_fts(qid, question, options, answer, explanation) VALUES (?,?,?,?,?)", chunk)
        chunk = []
if chunk:
    db.executemany("INSERT INTO question_fts(qid, question, options, answer, explanation) VALUES (?,?,?,?,?)", chunk)
for i, (qid,) in enumerate(ftsd):
    ftsd[i] = (i + 1, qid)   # contentless rowids are 1..N in insert order
db.executemany('INSERT INTO fts_doc VALUES (?,?)', ftsd)
print('FTS done', flush=True)

# ---------------- videos ----------------
series = {}
vids = []
for f in glob.glob(f'{API}/video_catalog/video_*.json'):
    m = re.match(r'video_(\d+)\.json$', os.path.basename(f))
    if not m:
        continue
    try:
        d = json.load(open(f))
    except Exception:
        continue
    fsid = int(m.group(1))
    for v in d.get('videos', []):
        y = dict(video_id=int(v.get('id') or 0),
                 series_id=fsid,
                 title=v.get('title') or '',
                 thumbnail_url=v.get('thumbnail_url') or '',
                 pdf_url=v.get('pdf_link') or '',
                 secret_key=v.get('secret_key') or '',
                 is_free=1 if str(v.get('is_free')).lower() in ('true', '1') else 0,
                 duration=v.get('duration') or '',
                 class_date=v.get('class_date') or '',
                 created_at=v.get('created_at') or '',
                 sort_order=int(v.get('order') or 0))
        vids.append(y)
# series from videoseries-subject-list
if os.path.exists(f'{API}/endpoints/videoseries-subject-list.json'):
    sd = json.load(open(f'{API}/endpoints/videoseries-subject-list.json'))
    for s in sd.get('videos', []):
        series[int(s.get('id') or 0)] = (int(s.get('type') or 0), s.get('title') or '')
db.executemany('INSERT INTO video_series VALUES (?,?,?)',
               [(sid, tp, tl) for sid, (tp, tl) in series.items()])
db.executemany('INSERT INTO video VALUES (?,?,?,?,?,?,?,?,?,?,?)',
               [(v['video_id'], v['series_id'], v['title'], v['thumbnail_url'],
                 v['pdf_url'], v['secret_key'], v['is_free'], v['duration'],
                 v['class_date'], v['created_at'], v['sort_order'])
                for v in sorted({v['video_id']: v for v in vids}.values(),
                                key=lambda x: x['video_id'])])
print(f'videos={len(vids)} series={len(series)}')

# ---------------- pdfs + media ---------------
if os.path.exists(f'{API}/media_manifest.tsv'):
    pdfs = []
    media = []
    import csv
    with open(f'{API}/media_manifest.tsv', encoding='utf-8') as fh:
        rd = csv.reader(fh, delimiter='\t')
        for i, row in enumerate(rd):
            if i == 0:
                continue
            if len(row) < 5:
                continue
            st, size, sha, relp, url = row[0], row[1], row[2], row[3], row[4]
            ext = (relp.split('.')[-1]).lower()
            kind = ext if ext in ('pdf', 'docx', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'svg', 'jfif') else 'other'
            media.append((relp, url, int(size or 0), sha, kind))
            if ext in ('pdf', 'docx'):
                pdfs.append((url, '', relp, int(size or 0), sha))
    db.executemany('INSERT INTO pdf VALUES (?,?,?,?,?)', pdfs)
    db.executemany('INSERT INTO media_url VALUES (?,?,?,?)',
                   [(p, sz, h, k) for p, u, sz, h, k in media])
    print(f'media={len(media)} pdf/docx={len(pdfs)}')

db.commit()
db.execute('ANALYZE')
db.commit()
db.close()
print(f'DONE — {OUT}  ({os.path.getsize(OUT)/1e6:.1f} MB) in {time.time()-t0:.0f}s')

# ============================================================ viewer data
# Compact JSON shards for the offline viewer (which reads api_data/exam_maps/
# itself, like the app fetched per-exam data).
import shutil, zipfile
VD = f'{ROOT}/viewer/data'
os.makedirs(f'{VD}/search', exist_ok=True)
os.makedirs(f'{ROOT}/viewer/fonts', exist_ok=True)
APK = f'{ROOT}/extracted/base.apk'
if os.path.exists(APK):
    with zipfile.ZipFile(APK) as z:
        for f in ('anek-bangla.ttf', 'Montserrat-Bold.ttf', 'kalpurush.ttf',
                  'notosans.ttf', 'notoserif.ttf'):
            src = f'assets/flutter_assets/assets/fonts/{f}'
            data = z.read(src)
            open(f'{ROOT}/viewer/fonts/{f}', 'wb').write(data)
    icon_src = glob.glob(f'{ROOT}/extracted/apk_base/res/mipmap-*/ic_launcher.png')
    shutil.copy(icon_src[0], f'{ROOT}/viewer/icon.png') if icon_src else None
else:
    print('WARN: base.apk missing; fonts/icon not refreshed')

exams_by_subj = {}
for eid, d in exams.items():
    info = exam_info.get(eid)
    exams_by_subj.setdefault(d.get('subject_id'), []).append(
        dict(id=eid, date=d.get('date'), qn=d.get('question_number'),
             omr=d.get('is_omr', 0), has=d.get('has_content', 0),
             title=d.get('title'),
             syl=re.sub(r'\s+', ' ', (info.get('syllabus') or '').strip()) if info
             and (info.get('syllabus') or '').strip() else None))
key_of = {r['qid']: k for k, r in qrows.items()}

subj_qids = {}
for eid, qid, pos, g in eq_rows:
    sid = exams.get(eid, {}).get('subject_id')
    if sid is not None:
        subj_qids.setdefault(sid, set()).add(qid)

_PREFIX_CLEAN = _PREFIX
def clean_q(text):
    return _PREFIX_CLEAN.sub('', text).strip()

def to_shard(qids):
    out = []
    for qid in qids:
        r = qrows[key_of[qid]]
        out.append(dict(q=clean_q(r['question']), o=json.loads(r['options_json'])[:4],
                        a=r['answer_index'], x=(r['explanation_html'] or '')[:260]))
    return out

course_idx = []
for sid, (name, slugs) in sorted(subjects.items()):
    excs = exams_by_subj.get(sid, [])
    qset = subj_qids.get(sid, set())
    json.dump(to_shard(qset), open(f'{VD}/search/search_{sid}.json', 'w'),
              ensure_ascii=False)
    json.dump(excs, open(f'{VD}/exams_{sid}.json', 'w'), ensure_ascii=False)
    course_idx.append(dict(id=sid, name=name, slug=slugs,
                           exams=len(excs), questions=len(qset)))
json.dump(course_idx, open(f'{VD}/courses_index.json', 'w'), ensure_ascii=False)

# orphan exams (job-solution / live / subject-final) not attached to any course
def _clean(t):
    return re.sub(r'\s+', ' ', (t or '').strip()) if (t or '').strip() else None
from collections import Counter
eq_count = Counter(eid for eid, _q, _p, _g in eq_rows)
extra = [dict(id=r['id'], date=r['date'], qn=eq_count.get(r['id'], 0),
              omr=r['omr'], has=1 if eq_count.get(r['id'], 0) else 0,
              title=_clean(r['title']) or '',
              syl=_clean(r['syl']))
         for r in exams_by_subj.get(None, [])]
json.dump(extra, open(f'{VD}/extra_exams.json', 'w'), ensure_ascii=False)
print(f'extra exams (not in any course): {len(extra)}')

# daily routine tab: every entry of the app's routine list, openable state included
_MONTHS = {m: i + 1 for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}
def _rdate(s):
    m = re.match(r'[A-Za-z]+, (\d{1,2}) ([A-Za-z]{3}), (\d{4})', s or '')
    if not m:
        return ''
    mo = _MONTHS.get(m.group(2))
    if not mo:
        return ''
    return f'{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}'
routine = []
if os.path.exists(f'{API}/routine_list_canonical.jsonl'):
    for line in open(f'{API}/routine_list_canonical.jsonl', encoding='utf-8'):
        try:
            r = json.loads(line)
        except Exception:
            continue
        eid = r.get('id')
        if eid is None:
            continue
        qn = eq_count.get(eid, 0)
        routine.append(dict(
            id=eid, date=r.get('date') or '', iso=_rdate(r.get('date') or ''),
            subj=r.get('subject_name') or '', mark=r.get('mark') or '',
            time=r.get('examtime') or '', qn=qn, has=1 if qn else 0,
            today=1 if r.get('is_today') else 0,
            title=_clean(exams.get(eid, {}).get('title')) or ''))
json.dump(routine, open(f'{VD}/routine.json', 'w'), ensure_ascii=False)
print(f'routine exams listed: {len(routine)}')

# full bank search shard (all questions that also live in the 80k bank feed)
bank_qids = [q['qid'] for q in qrows.values() if q['has_bank']]
json.dump(to_shard(bank_qids), open(f'{VD}/search/search_bank.json', 'w'),
          ensure_ascii=False)

# routine/extras scope: questions that appear only in course-less exams
# (subject_id NULL) — those are in the DB but in no per-course shard nor the bank.
extra_qids = []
seen_x = set()
for eid, qid, _p, _g in eq_rows:
    if exams.get(eid, {}).get('subject_id') is None and qid not in seen_x:
        seen_x.add(qid)
        extra_qids.append(qid)
json.dump(to_shard(extra_qids), open(f'{VD}/search/search_routine.json', 'w'),
          ensure_ascii=False)
print(f'search routine scope: {len(extra_qids)} questions')

# exam name lookup for the exam view (title + syllabus of the same exam id)
json.dump({str(eid): dict(t=d.get('title') or '',
                          s=re.sub(r'\s+', ' ', (exam_info[eid].get('syllabus') or '').strip())
                          if eid in exam_info and (exam_info[eid].get('syllabus') or '').strip()
                          else '')
           for eid, d in exams.items()},
          open(f'{VD}/exam_titles.json', 'w'), ensure_ascii=False)

# videos index (grouped by series) + pdfs index
uniq_vids = {v['video_id']: v
             for v in sorted(vids, key=lambda x: (x['series_id'] or 0, x['sort_order']))}
vids_by_series = {}
for v in sorted(uniq_vids.values(), key=lambda x: (x['series_id'] or 0, x['sort_order'])):
    vids_by_series.setdefault(v['series_id'], []).append(
        dict(id=v['video_id'], t=v['title'], th=v['thumbnail_url'],
             p=v['pdf_url'], free=v['is_free'], dur=v['duration'],
             date=v['class_date']))
ser = [dict(id=sid, type=tp, title=tl, count=len(vids_by_series.get(sid, [])))
       for sid, (tp, tl) in sorted(series.items())]
json.dump([dict(s=s, videos=vids_by_series.get(s['id'], [])) for s in ser],
          open(f'{VD}/videos_index.json', 'w'), ensure_ascii=False)

pdf_idx = [dict(u=u, p=p, n=os.path.basename(p), sz=sb)
           for u, t, p, sb, h in pdfs]
json.dump(sorted(pdf_idx, key=lambda x: x['n']), open(f'{VD}/pdfs_index.json', 'w'),
          ensure_ascii=False)

# url -> rel_path (thumbnail/pdf lookup in the browser, ~35k entries, compact)
media_url = {u: p for p, u, sz, h, k in media}
json.dump(media_url, open(f'{VD}/media_url.json', 'w'), ensure_ascii=False)

about = dict(courses=len(course_idx), exams=len(exams), questions=len(qrows),
             bank=len(bank_qids), exam_questions=len(eq_rows),
             videos=len({v['video_id'] for v in vids}),
             series=len(series), pdfs=len(pdfs), media=len(media),
             routine=len(routine))
json.dump(about, open(f'{VD}/about.json', 'w'), ensure_ascii=False)

# Recover the video stream URLs (deterministic CDN pattern, see
# docs/VIDEO_RECOVERY.md). Regenerated here so a full rebuild doesn't drop
# viewer/data/video_streams.json. Non-fatal: the viewer degrades to hiding the
# play chips if the file is absent.
try:
    import make_video_urls
    _argv = sys.argv
    sys.argv = ['make_video_urls.py']
    try:
        make_video_urls.main()
    finally:
        sys.argv = _argv
except Exception as e:
    print('video stream inventory skipped:', e)

print('viewer data written to', VD)