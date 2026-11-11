"""SQLite-Datenhaltung. Eine Verbindung je Aufruf, damit Threads sich nicht in die Quere kommen."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sites (
  id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL DEFAULT 1,
  name TEXT NOT NULL, url TEXT NOT NULL, domain TEXT NOT NULL,
  aliases TEXT NOT NULL DEFAULT '[]', language TEXT DEFAULT 'de',
  interval TEXT NOT NULL DEFAULT 'monthly', next_run_at TEXT,
  auto_start INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'analysing', state_msg TEXT DEFAULT '',
  profile TEXT DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, name TEXT NOT NULL,
  position INTEGER DEFAULT 0, merged_into INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, topic_id INTEGER NOT NULL,
  code TEXT NOT NULL, text TEXT NOT NULL, lang TEXT DEFAULT 'de',
  is_brand INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
  revision INTEGER DEFAULT 1, series_start TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
  topic_id INTEGER, question_id INTEGER, detail TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
  mode TEXT NOT NULL DEFAULT 'live', trigger TEXT DEFAULT 'manual',
  queued_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  progress INTEGER DEFAULT 0, step TEXT DEFAULT '', audit TEXT, summary TEXT,
  channels TEXT, error TEXT, change_mark INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS run_questions (
  run_id INTEGER NOT NULL, question_id INTEGER NOT NULL, code TEXT, text TEXT, lang TEXT,
  is_brand INTEGER, revision INTEGER, topic_id INTEGER, topic_name TEXT,
  PRIMARY KEY (run_id, question_id));
CREATE TABLE IF NOT EXISTS answers (
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, question_id INTEGER NOT NULL,
  channel TEXT NOT NULL, status TEXT NOT NULL, text TEXT DEFAULT '',
  citations TEXT DEFAULT '[]', mentioned INTEGER DEFAULT 0, cited INTEGER DEFAULT 0,
  rank INTEGER, vendors_done INTEGER DEFAULT 0, hint TEXT, error TEXT, created_at TEXT,
  UNIQUE (run_id, question_id, channel));
CREATE TABLE IF NOT EXISTS vendors (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL,
  hidden INTEGER DEFAULT 0, merged_into INTEGER, created_at TEXT NOT NULL,
  UNIQUE (site_id, key));
CREATE TABLE IF NOT EXISTS answer_vendors (
  answer_id INTEGER NOT NULL, vendor_id INTEGER NOT NULL, pos INTEGER,
  PRIMARY KEY (answer_id, vendor_id));
CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, prio INTEGER, key TEXT, title TEXT,
  level TEXT, effort TEXT, place TEXT, evidence TEXT, action TEXT, draft TEXT);
CREATE INDEX IF NOT EXISTS ix_answers_run ON answers(run_id);
CREATE INDEX IF NOT EXISTS ix_runs_site ON runs(site_id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=OFF")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO tenants (id, name) VALUES (1, 'Intern')")


def q(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def x(sql, args=()):
    with conn() as c:
        return c.execute(sql, args).lastrowid


def log_change(site_id, kind, topic_id=None, question_id=None, **detail):
    x("INSERT INTO changes (site_id, at, kind, topic_id, question_id, detail) VALUES (?,?,?,?,?,?)",
      (site_id, now(), kind, topic_id, question_id, json.dumps(detail, ensure_ascii=False)))


def jload(s, default=None):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default
