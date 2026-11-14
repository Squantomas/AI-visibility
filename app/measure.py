"""Messlauf: Fragen einfrieren, Technik prüfen, alle Kanäle abfragen, Anbieter erkennen, Empfehlungen bilden.

Ein Lauf ist wiederaufnehmbar: Was schon gespeichert ist, wird nicht noch einmal abgefragt.
"""
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import channels, config, crawl, db, llm, questions
from .textutil import alias_patterns, is_alias, mentions, same_site, vendor_key

INTERVALS = {"none": "kein Rhythmus", "weekly": "wöchentlich", "biweekly": "alle 14 Tage",
             "monthly": "monatlich", "quarterly": "vierteljährlich"}

VENDOR_SYSTEM = """Du wertest Antworten von KI-Assistenten aus. Zu einer Frage liegen mehrere Antworten vor.
Nenne je Antwort die Unternehmen oder Marken, die dort als Anbieter, Hersteller, Lieferanten oder Dienstleister
für das gefragte Anliegen genannt werden, in der Reihenfolge der ersten Nennung.
Nicht aufnehmen: Verzeichnisse, Marktplätze, Medien, Verbände, Normen, reine Quellenangaben und Kunden der Anbieter.
Verwende den gebräuchlichen Kurznamen ohne Rechtsform und schreibe denselben Anbieter immer gleich."""


def next_run(interval, start_iso):
    start = datetime.fromisoformat(start_iso)
    if interval in ("weekly", "biweekly"):
        return (start + timedelta(days=7 if interval == "weekly" else 14)).isoformat(timespec="seconds")
    if interval in ("monthly", "quarterly"):
        m = start.month - 1 + (1 if interval == "monthly" else 3)
        return start.replace(year=start.year + m // 12, month=m % 12 + 1, day=min(start.day, 28)).isoformat(timespec="seconds")
    return None


def enqueue(site_id, trigger="manual"):
    open_ = db.one("SELECT id FROM runs WHERE site_id=? AND status IN ('queued','running')", (site_id,))
    if open_:
        return open_["id"]
    mode = "demo" if config.demo_mode() else "live"
    return db.x("INSERT INTO runs (site_id, status, mode, trigger, queued_at) VALUES (?,?,?,?,?)",
                (site_id, "queued", mode, trigger, db.now()))


def retry_failed(run_id):
    """Fehlgeschlagene Abfragen eines Laufs verwerfen und den Lauf erneut einreihen."""
    db.x("DELETE FROM answers WHERE run_id=? AND status IN ('error', 'skipped')", (run_id,))
    db.x("UPDATE runs SET status='queued', error=NULL WHERE id=?", (run_id,))


def _progress(run_id, pct, step):
    db.x("UPDATE runs SET progress=?, step=? WHERE id=?", (pct, step, run_id))


def score_answer(site, channel, text, citations):
    """-> (genannt, als Quelle zitiert, Rang in der Websuche)"""
    domain = site["domain"]
    if channel == "web":
        for i, u in enumerate(citations[:10]):
            if same_site(u, domain):
                return 1, 1, i + 1
        return 0, 0, None
    pats = alias_patterns(db.jload(site["aliases"], []), domain)
    return int(mentions(text, pats)), int(any(same_site(u, domain) for u in citations)), None


def recompute_mentions(site_id):
    """Nach einer Änderung der Markenschreibweisen: Treffer aller Läufe neu bestimmen."""
    site = db.one("SELECT * FROM sites WHERE id=?", (site_id,))
    rows = db.q("SELECT a.id, a.channel, a.text, a.citations FROM answers a JOIN runs r ON r.id=a.run_id "
                "WHERE r.site_id=? AND a.status='ok'", (site_id,))
    with db.conn() as c:
        for a in rows:
            m, cited, rank = score_answer(site, a["channel"], a["text"], db.jload(a["citations"], []))
            if a["channel"] == "web":
                c.execute("UPDATE answers SET mentioned=?, cited=?, rank=? WHERE id=?", (m, cited, rank, a["id"]))
            else:
                c.execute("UPDATE answers SET mentioned=?, cited=? WHERE id=?", (m, cited, a["id"]))


def execute(run_id):
    run = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    site = db.one("SELECT * FROM sites WHERE id=?", (run["site_id"],))
    try:
        db.x("UPDATE runs SET status='running', started_at=COALESCE(started_at, ?) WHERE id=?", (db.now(), run_id))
        _snapshot(run_id, site["id"])
        qs = db.q("SELECT * FROM run_questions WHERE run_id=? ORDER BY question_id", (run_id,))
        if not qs:
            raise RuntimeError("Keine aktiven Fragen vorhanden")

        if not run["audit"]:
            _progress(run_id, 3, "Technik der Website prüfen")
            data = crawl.crawl(site["url"])
            db.x("UPDATE runs SET audit=? WHERE id=?",
                 (json.dumps({"checks": crawl.audit(data), "pages": len(data.get("pages", []))}, ensure_ascii=False), run_id))

        status = config.channel_status()
        db.x("UPDATE runs SET channels=? WHERE id=?",
             (json.dumps({k: {"ready": v[0], "note": v[1]} for k, v in status.items()}, ensure_ascii=False), run_id))
        _ask_all(run_id, site, qs, status)

        if not db.one("SELECT 1 AS x FROM answers WHERE run_id=? AND status='ok'", (run_id,)):
            raise RuntimeError("Kein Kanal hat eine Antwort geliefert. Bitte Schlüssel und Netzzugang unter "
                               "„Kanäle & Einstellungen“ prüfen.")

        _progress(run_id, 85, "Anbieter in den Antworten erkennen")
        extract_vendors(run_id, site, qs)

        _progress(run_id, 93, "Empfehlungen ableiten")
        from . import recommend
        recommend.build(run_id)

        started = db.one("SELECT started_at FROM runs WHERE id=?", (run_id,))["started_at"]
        db.x("UPDATE runs SET status='done', progress=100, step='Fertig', finished_at=? WHERE id=?", (db.now(), run_id))
        db.x("UPDATE sites SET state='active', next_run_at=? WHERE id=?", (next_run(site["interval"], started), site["id"]))
    except Exception as e:
        traceback.print_exc()
        db.x("UPDATE runs SET status='failed', error=?, finished_at=? WHERE id=?", (str(e)[:500], db.now(), run_id))
        # Auch nach einem Fehlschlag weiter im Rhythmus bleiben
        db.x("UPDATE sites SET next_run_at=? WHERE id=?", (next_run(site["interval"], db.now()), site["id"]))


def _snapshot(run_id, site_id):
    """Fragen und Themenfelder zum Zeitpunkt des Laufs festhalten."""
    if db.one("SELECT 1 AS x FROM run_questions WHERE run_id=?", (run_id,)):
        return
    rows = db.q("SELECT q.*, t.name AS topic_name FROM questions q JOIN topics t ON t.id=q.topic_id "
                "WHERE q.site_id=? AND q.active=1", (site_id,))
    # Stand des Änderungsprotokolls merken: Der Bericht zeigt, was seit dem vorigen Lauf geändert wurde.
    mark = db.one("SELECT COALESCE(MAX(id), 0) AS m FROM changes WHERE site_id=?", (site_id,))["m"]
    db.x("UPDATE runs SET change_mark=? WHERE id=?", (mark, run_id))
    with db.conn() as c:
        for r in rows:
            c.execute("INSERT INTO run_questions VALUES (?,?,?,?,?,?,?,?,?)",
                      (run_id, r["id"], r["code"], r["text"], r["lang"], r["is_brand"], r["revision"],
                       r["topic_id"], r["topic_name"]))


def _ask_all(run_id, site, qs, status):
    seq = db.one("SELECT COUNT(*) AS n FROM runs WHERE site_id=? AND status='done'", (site["id"],))["n"]
    ctx = {"site": site, "run_seq": seq}
    have = {(a["question_id"], a["channel"]) for a in db.q("SELECT question_id, channel FROM answers WHERE run_id=?", (run_id,))}
    total = len(qs) * len(config.CHANNELS)
    done = [len(have)]
    lock = threading.Lock()

    def store(qu, channel, st, res=None, error=None):
        res = res or {"text": "", "citations": [], "hint": None}
        m, cited, rank = score_answer(site, channel, res["text"], res["citations"]) if st == "ok" else (0, 0, None)
        db.x("INSERT OR REPLACE INTO answers (run_id, question_id, channel, status, text, citations, mentioned, cited, "
             "rank, hint, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
             (run_id, qu["question_id"], channel, st, res["text"], json.dumps(res["citations"]), m, cited, rank,
              json.dumps(res["hint"], ensure_ascii=False) if res["hint"] is not None else None, error, db.now()))
        with lock:
            done[0] += 1
            _progress(run_id, 5 + int(78 * done[0] / total), f"Abfragen: {done[0]} von {total}")

    def one(args):
        qu, channel = args
        try:
            store(qu, channel, "ok", channels.ask(channel, qu, ctx))
        except Exception as e:
            store(qu, channel, "error", error=str(e)[:400])

    def run_channel(channel):
        todo = [(qu, channel) for qu in qs if (qu["question_id"], channel) not in have]
        if not status[channel][0]:
            for qu, _ in todo:
                store(qu, channel, "skipped", error=status[channel][1])
            return
        workers = 1 if channel in ("copilot", "web") else 3
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, todo))

    with ThreadPoolExecutor(max_workers=len(config.CHANNELS)) as pool:
        list(pool.map(run_channel, [c["key"] for c in config.CHANNELS]))


def extract_vendors(run_id, site, qs):
    """Je Frage die genannten Anbieter bestimmen und den Rang der eigenen Marke festhalten."""
    provider = None if config.demo_mode() else config.analysis_provider()
    aliases = db.jload(site["aliases"], [])

    def handle(qu):
        ans = db.q("SELECT * FROM answers WHERE run_id=? AND question_id=? AND status='ok' AND channel!='web' "
                   "AND vendors_done=0", (run_id, qu["question_id"]))
        if not ans or qu["is_brand"]:
            return
        names = {a["id"]: db.jload(a["hint"]) for a in ans}
        missing = [a for a in ans if names[a["id"]] is None]
        if missing and provider:
            block = "\n\n".join(f"=== Antwort {a['channel']} ===\n{a['text'][:6000]}" for a in missing)
            try:
                res = llm.analyse(provider, VENDOR_SYSTEM,
                                  f"Frage: {qu['text']}\n\n{block}\n\nAntwortformat (JSON): "
                                  '{"answers": {"<kanal>": ["Anbieter 1", "Anbieter 2"]}}')
                got = res.get("answers", {})
                for a in missing:
                    names[a["id"]] = [n for n in got.get(a["channel"], []) if isinstance(n, str)]
            except Exception:
                pass
        for a in ans:
            if names[a["id"]] is None:
                continue  # nicht auswertbar; bleibt für einen späteren Versuch offen
            save_vendors(site["id"], a["id"], names[a["id"]], aliases, site["domain"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(handle, qs))


def save_vendors(site_id, answer_id, names, aliases, domain):
    rank, pos = None, 0
    with db.conn() as c:
        for n in names:
            key = vendor_key(n)
            if not key:
                continue
            pos += 1
            if is_alias(n, aliases, domain):
                rank = rank or pos
                continue
            c.execute("INSERT OR IGNORE INTO vendors (site_id, name, key, created_at) VALUES (?,?,?,?)",
                      (site_id, n.strip()[:80], key, db.now()))
            vid = c.execute("SELECT id FROM vendors WHERE site_id=? AND key=?", (site_id, key)).fetchone()["id"]
            c.execute("INSERT OR IGNORE INTO answer_vendors VALUES (?,?,?)", (answer_id, vid, pos))
        c.execute("UPDATE answers SET vendors_done=1, rank=? WHERE id=?", (rank, answer_id))


# ---------- Zeitplanung ----------

def scheduler_tick():
    """Fällige Websites einreihen und den nächsten wartenden Lauf ausführen."""
    for s in db.q("SELECT id FROM sites WHERE state='active' AND interval!='none' AND next_run_at IS NOT NULL "
                  "AND next_run_at<=?", (db.now(),)):
        enqueue(s["id"], "schedule")
    run = db.one("SELECT id FROM runs WHERE status='queued' ORDER BY id LIMIT 1")
    if run:
        execute(run["id"])
        return True
    return False


def start_worker():
    # Läufe, die beim letzten Beenden mittendrin waren, werden fortgesetzt.
    db.x("UPDATE runs SET status='queued' WHERE status='running'")
    for s in db.q("SELECT id FROM sites WHERE state='analysing'"):
        threading.Thread(target=questions.analyse_site, args=(s["id"],), daemon=True).start()

    def loop():
        while True:
            try:
                if not scheduler_tick():
                    time.sleep(5)
            except Exception:
                traceback.print_exc()
                time.sleep(15)

    threading.Thread(target=loop, daemon=True, name="ai-visibility-worker").start()
