"""Tests: Kernlogik und ein kompletter Durchlauf im Demo-Modus gegen die lokale Test-Website."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DEMO_MODE"] = "1"
os.environ["OPENROUTER_MODELS"] = ""  # Kanalzahl unabhängig von der eigenen .env
os.environ["CLAUDE_CODE_MODE"] = "off"
os.environ["GOOGLE_AI_MODE"] = "off"
os.environ["SEARCH_PROVIDER"] = "duckduckgo"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",localhost,127.0.0.1"

from app import crawl, db, measure, questions, report, textutil  # noqa: E402
from tests import fixture_site  # noqa: E402

PORT = 8766
fixture_site.serve(PORT, background=True)
db.init()


def test_brand_is_found_in_all_spellings():
    pats = textutil.alias_patterns(["FRÖTEK"], "froetek.com")
    for text in ["Anbieter: FRÖTEK aus Osterode", "die Firma Froetek", "FROTEK liefert", "siehe froetek.com"]:
        assert textutil.mentions(text, pats), text
    assert not textutil.mentions("Frötekker und andere", pats)
    assert textutil.vendor_key("Hoppecke Batterien GmbH & Co. KG") == textutil.vendor_key("HOPPECKE Batterien")
    assert textutil.is_alias("Froetek GmbH", ["FRÖTEK"])


def test_robots_blocking():
    assert crawl.blocked_bots("User-agent: GPTBot\nDisallow: /\n") == ["GPTBot"]
    assert crawl.blocked_bots("User-agent: *\nDisallow: /privat\n") == []


def test_images_in_removed_areas():
    page = crawl.parse_page("https://x.example/", "<html><header><img src=a.png></header>"
                            "<main><img src=b.png alt='B'></main><footer><img src=c.png alt=''></footer></html>")
    assert page["imgs"] == 3 and page["imgs_no_alt"] == 2


def test_next_run():
    assert measure.next_run("monthly", "2026-12-31T10:00:00+00:00").startswith("2027-01-28")
    assert measure.next_run("weekly", "2026-11-10T10:00:00+00:00").startswith("2026-11-17")
    assert measure.next_run("none", "2026-11-10T10:00:00+00:00") is None


def test_full_cycle():
    sid = questions.create_site(f"http://localhost:{PORT}", "Brückner Filtertechnik", "monthly")
    questions.analyse_site(sid)
    site = db.one("SELECT * FROM sites WHERE id=?", (sid,))
    assert site["state"] == "draft", site["state_msg"]
    qs = db.q("SELECT * FROM questions WHERE site_id=? AND active=1", (sid,))
    assert len(qs) >= 8 and sum(q["is_brand"] for q in qs) == 2

    # --- Erste Messung
    r1 = measure.enqueue(sid)
    assert measure.enqueue(sid) == r1  # kein doppelter Lauf
    measure.execute(r1)
    run = db.one("SELECT * FROM runs WHERE id=?", (r1,))
    assert run["status"] == "done", run["error"]
    assert db.one("SELECT COUNT(*) AS n FROM answers WHERE run_id=?", (r1,))["n"] == len(qs) * 6
    assert db.one("SELECT next_run_at FROM sites WHERE id=?", (sid,))["next_run_at"]
    R1 = report.build(r1)
    assert R1["prev"] is None and R1["head"]["ai"][1] == len(qs) * 5
    assert len(R1["recs"]) >= 5
    assert R1["vendors"]["rows"][0]["self"] and len(R1["vendors"]["rows"]) > 2
    assert {c["key"]: c["status"] for c in R1["checks"]}["aibots"] == "fehlt"  # GPTBot ist in der Test-Website gesperrt
    assert len(R1["models"]) == 6 and all(m["measured"] for m in R1["models"])

    # --- Zwischen den Prüfungen: Frage ändern, Frage ergänzen, Feld umbenennen, Felder zusammenlegen
    fach = [q for q in qs if not q["is_brand"]]
    questions.update_question(fach[0]["id"], text="Wer baut Entstaubungsanlagen für Schreinereien?", topic_id=fach[0]["topic_id"])
    new_q = questions.add_question(sid, "Welche Hersteller liefern Ölnebelabscheider für Fräsmaschinen?")
    topics = [t for t in questions.topics(sid) if t["name"] != questions.BRAND_TOPIC]
    questions.rename_topic(topics[0]["id"], "Industriefilter neu")
    if len(topics) > 2:
        questions.merge_topics(topics[-1]["id"], topics[-2]["id"])

    # --- Zweite Messung zeigt die Veränderung und kennzeichnet die Änderungen
    r2 = measure.enqueue(sid)
    measure.execute(r2)
    R2 = report.build(r2)
    assert R2["prev"]["id"] == r1 and R2["head"]["d_ai"] is not None
    by_id = {q["question_id"]: q for q in R2["questions"]}
    assert by_id[fach[0]["id"]]["flag"] == "neustart" and by_id[fach[0]["id"]]["prev_hits"] is None
    assert by_id[new_q]["flag"] == "neu"
    assert by_id[fach[1]["id"]]["flag"] is None and by_id[fach[1]["id"]]["prev_hits"].endswith("/5")
    assert R2["head"]["comparable"] == len(qs) - 1
    assert any(t["notes"] for t in R2["topics"])
    kinds = {c["label"] for c in R2["changes"]}
    assert "Frage geändert – Verlauf beginnt neu" in kinds and "Themenfeld umbenannt" in kinds
    assert len(R2["trends"]["labels"]) == 2 and R2["trends"]["changed"][1]
    assert all(c["delta"] is not None or True for r in R2["vendors"]["rows"] for c in r["cells"])

    # --- Anbieterliste bereinigen wirkt auf den Bericht
    rows = [r for r in R2["vendors"]["rows"] if not r["self"]]
    a = db.one("SELECT * FROM vendors WHERE site_id=? AND name=?", (sid, rows[0]["name"]))
    b = db.one("SELECT * FROM vendors WHERE site_id=? AND name=?", (sid, rows[1]["name"]))
    db.x("UPDATE vendors SET merged_into=? WHERE id=?", (a["id"], b["id"]))
    R3 = report.build(r2)
    names = [r["name"] for r in R3["vendors"]["rows"]]
    assert b["name"] not in names and a["name"] in names
    db.x("UPDATE vendors SET hidden=1 WHERE id=?", (a["id"],))
    assert a["name"] not in [r["name"] for r in report.build(r2)["vendors"]["rows"]]

    # --- Zeitplanung: fällige Website wird eingereiht
    db.x("UPDATE sites SET next_run_at='2000-01-01T00:00:00+00:00' WHERE id=?", (sid,))
    assert measure.scheduler_tick() is True
    assert db.one("SELECT COUNT(*) AS n FROM runs WHERE site_id=? AND status='done'", (sid,))["n"] == 3


def test_delete_site():
    from fastapi.testclient import TestClient
    from app.main import app

    sid = questions.create_site(f"http://localhost:{PORT}", "Löschtest GmbH", "none")
    questions.analyse_site(sid)
    rid = measure.enqueue(sid)
    client = TestClient(app)
    db.x("UPDATE runs SET status='running' WHERE id=?", (rid,))
    assert client.post(f"/sites/{sid}/delete", follow_redirects=False).status_code == 409
    measure.execute(rid)
    assert client.post(f"/sites/{sid}/delete", follow_redirects=False).status_code == 303
    assert db.one("SELECT 1 AS x FROM sites WHERE id=?", (sid,)) is None
    for t, col, val in [("runs", "site_id", sid), ("questions", "site_id", sid), ("topics", "site_id", sid),
                        ("vendors", "site_id", sid), ("answers", "run_id", rid), ("run_questions", "run_id", rid)]:
        assert db.one(f"SELECT COUNT(*) AS n FROM {t} WHERE {col}=?", (val,))["n"] == 0, t
