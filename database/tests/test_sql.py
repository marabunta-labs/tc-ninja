"""Runs schema.sql and the migrations against a real embedded Postgres + pgvector.

    uv venv --python 3.12 /tmp/sqlenv && uv pip install --python /tmp/sqlenv/bin/python pgserver psycopg2-binary numpy
    /tmp/sqlenv/bin/python database/tests/test_sql.py

(pgserver has no wheels for Python 3.13 yet, hence 3.12.) Covers: legacy upgrade 001 → 002,
idempotent schema.sql, atomic activation, one-current-version index, hybrid search
(current-only, version filter, embedding-model mismatch, hostile query strings), cascade purge.
"""
import hashlib, json, pathlib, re, sys, tempfile
import numpy as np, pgserver, psycopg2
HERE = pathlib.Path(__file__).parent
ROOT = str(HERE.parent) + "/"
S = str(HERE) + "/"

def vec(text):
    v = np.zeros(384)
    for w in re.findall(r"\w+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1
    n = np.linalg.norm(v); return (v / n if n else v)
lit = lambda v: "[" + ",".join(f"{x:.6f}" for x in v) + "]"

def connect(name):
    srv = pgserver.get_server(tempfile.mkdtemp(prefix=name), cleanup_mode="stop")
    conn = psycopg2.connect(srv.get_uri()); conn.autocommit = True
    cur = conn.cursor()
    for r in ("anon", "authenticated"):
        cur.execute(f"DO $$ BEGIN CREATE ROLE {r}; EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    return srv, conn, cur

def run(cur, path):
    cur.execute(open(path).read())

def add_doc(cur, platform, lang, text, meta, version_id=None):
    cur.execute("INSERT INTO documents (platform, language, content, metadata, embedding" + (", version_id" if version_id else "") + ") VALUES (%s,%s,%s,%s,%s" + (",%s" if version_id else "") + ")",
                [platform, lang, text, json.dumps(meta), lit(vec((meta.get("section", "") + " " + text)))] + ([version_id] if version_id else []))

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name, extra)
    if not cond: check.failed += 1
check.failed = 0

# ---------------- A: upgrade of a legacy database ----------------
srv, conn, cur = connect("legacy")
run(cur, S + "legacy_schema.sql")
old = "We keep your data for 12 months maximum."
new = "We keep your data for 30 days only."
add_doc(cur, "Telegram", "en", "Unversioned legacy row about cookies.", {"source_url": "https://t.org/tos"})
for v, txt, h in (("2026-03-01", old, "h1"), ("2026-09-01", new, "h2")):
    add_doc(cur, "Telegram", "en", txt, {"version": v, "fetch_date": v, "content_hash": h, "source_url": "https://t.org/tos"})
run(cur, ROOT + "migrations/001_document_versions.sql")
cur.execute("select version,status from document_versions order by id"); rows = cur.fetchall()
check("001 backfill: one current per pair", sum(1 for r in rows if r[1] == "current") == 1, rows)
cur.execute("select count(*) from documents where version_id is null"); check("001: no orphan chunks", cur.fetchone()[0] == 0)
run(cur, ROOT + "migrations/002_hybrid_search_and_changes.sql")
cur.execute("select distinct embedding_model from document_versions"); check("002: legacy rows tagged minilm", cur.fetchall() == [("paraphrase-multilingual-MiniLM-L12-v2",)])
cur.execute("select count(*) from documents where fts is null"); check("002: fts populated", cur.fetchone()[0] == 0)
cur.execute("select content, version_status from match_documents_hybrid(%s::vector, %s, 5, ARRAY['Telegram'], 'en')", [lit(vec("how long keep data")), "how long do they keep my data"])
r = cur.fetchall(); check("hybrid returns only current version", [x[1] for x in r] and set(x[1] for x in r) == {"current"}, r)
cur.execute("select content from match_documents_hybrid(%s::vector, %s, 5, ARRAY['Telegram'], 'en', NULL, 'multilingual-e5-small')", [lit(vec("zzz")), "keep data days"])
r = cur.fetchall(); check("model mismatch: full-text half still finds legacy rows", any("30 days" in x[0] for x in r), r)
cur.execute("select content, version_status from match_documents_hybrid(%s::vector, %s, 5, ARRAY['Telegram'], 'en', '2026-03-01')", [lit(vec("keep data")), "keep data"])
r = cur.fetchall(); check("version filter reaches superseded", r and r[0][1] == "superseded", r)
for q in ["what's 'this': a & b | c!", "((", "", "!!! ???", "a:*b", "\"quoted\" -minus OR"]:
    try:
        cur.execute("select count(*) from match_documents_hybrid(%s::vector, %s, 5, ARRAY['Telegram'], 'en')", [lit(vec("x")), q]); ok = True
    except Exception as e: ok = False; print("   err", repr(q), str(e)[:100])
    check(f"hybrid survives query {q!r}", ok)
srv.cleanup()

# ---------------- B: fresh install, idempotency, atomic activation ----------------
srv, conn, cur = connect("fresh")
run(cur, ROOT + "schema.sql"); run(cur, ROOT + "schema.sql"); check("schema.sql is re-runnable", True)
def version(v, status="pending"):
    cur.execute("insert into document_versions (platform,language,version,status,content_hash,embedding_model) values ('TikTok','es',%s,%s,'h','multilingual-e5-small') returning id", [v, status]); return cur.fetchone()[0]
v1 = version("2026-01-01"); add_doc(cur, "TikTok", "es", "Conservamos tus datos durante doce meses.", {"section": "Retención de datos"}, v1)
cur.execute("select count(*) from match_documents_hybrid(%s::vector, 'datos', 5, ARRAY['TikTok'], 'es')", [lit(vec("datos"))]); check("pending version is never searchable", cur.fetchone()[0] == 0)
cur.execute("select activate_document_version(%s)", [v1])
v2 = version("2026-02-01"); add_doc(cur, "TikTok", "es", "Conservamos tus datos durante treinta días.", {"section": "Retención de datos"}, v2)
cur.execute("select activate_document_version(%s)", [v2])
cur.execute("select version,status from document_versions order by id"); check("activation deprecates previous", cur.fetchall() == [("2026-01-01", "superseded"), ("2026-02-01", "current")])
cur.execute("select content from match_documents_hybrid(%s::vector, '¿Cuánto tiempo conservan mis datos?', 5, ARRAY['TikTok'], 'es', NULL, 'multilingual-e5-small')", [lit(vec("conservamos datos"))])
r = cur.fetchall(); check("spanish hybrid returns current clause", len(r) == 1 and "treinta" in r[0][0], r)
try:
    cur.execute("insert into document_versions (platform,language,version,status,content_hash) values ('TikTok','es','x','current','h')"); ok = False
except psycopg2.errors.UniqueViolation: ok = True
check("unique index blocks two current versions", ok)
cur.execute("delete from document_versions where id=%s", [v1]); cur.execute("select count(*) from documents where version_id=%s", [v1]); check("purge cascades to chunks", cur.fetchone()[0] == 0)
srv.cleanup()
print("FAILED:", check.failed); sys.exit(1 if check.failed else 0)
