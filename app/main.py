"""Weboberfläche (FastAPI). Start: python run.py"""
import base64
import json
import secrets
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import __version__, channels, config, db, measure, questions, report
from .config import env

BASE = Path(__file__).parent
TENANT = 1  # heute fest; die Tabellen tragen tenant_id, damit später Kundenkonten möglich sind

app = FastAPI(title="AI-Visibility", version=__version__)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
tpl = Jinja2Templates(directory=BASE / "templates")


@app.on_event("startup")
def startup():
    db.init()
    measure.start_worker()


@app.middleware("http")
async def password(request: Request, call_next):
    pw = env("APP_PASSWORD")
    if pw:
        try:
            given = base64.b64decode(request.headers.get("authorization", "").split(" ", 1)[1]).decode().split(":", 1)[1]
        except Exception:
            given = ""
        if not secrets.compare_digest(given.encode(), pw.encode()):
            return Response("Anmeldung nötig", 401, {"WWW-Authenticate": 'Basic realm="AI-Visibility"'})
    return await call_next(request)


# ---------- Darstellungshelfer ----------

def fmt_date(s, time=False):
    if not s:
        return "–"
    d = datetime.fromisoformat(s).astimezone()
    return d.strftime("%d.%m.%Y %H:%M" if time else "%d.%m.%Y")


def fmt_delta(v, unit=" PP"):
    if v is None:
        return Markup('<span class="d d0">–</span>')
    cls, sym = ("up", "▲") if v > 0 else (("down", "▼") if v < 0 else ("d0", "●"))
    return Markup(f'<span class="d {cls}">{sym} {v:+d}{unit}</span>' if v else '<span class="d d0">± 0</span>')


def linechart(values, labels, changed=None, w=250, h=108):
    """Kleine Verlaufsgrafik (0–100 %) als SVG. Eine Reihe je Grafik, letzte Messung beschriftet."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    left, right, top, bottom = 8, 44, 10, 30
    iw, ih = w - left - right, h - top - bottom
    n = max(len(values) - 1, 1)
    X = lambda i: left + (iw * i / n if len(values) > 1 else iw / 2)
    Y = lambda v: top + ih * (1 - v / 100)
    s = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" class="chart">']
    for g in (0, 50, 100):
        s.append(f'<line x1="{left}" x2="{left + iw}" y1="{Y(g)}" y2="{Y(g)}" class="grid"/>')
    for i, c in enumerate(changed or []):
        if c:
            s.append(f'<path d="M{X(i)} {h - 27} l4 5 l-4 5 l-4 -5z" class="chg"><title>{labels[i]}: Fragenkatalog geändert</title></path>')
    if len(pts) > 1:
        s.append('<polyline class="line" points="' + " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in pts) + '"/>')
    for i, v in pts:
        s.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" class="pt"><title>{labels[i]}: {v} %</title></circle>')
    if len(labels) > 1:
        de = lambda d: f"{d[8:10]}.{d[5:7]}.{d[2:4]}"
        s.append(f'<text x="{left}" y="{h - 3}" class="ax">{de(labels[0])}</text>')
        s.append(f'<text x="{left + iw}" y="{h - 3}" class="ax" text-anchor="end">{de(labels[-1])}</text>')
    if pts:
        i, v = pts[-1]
        s.append(f'<text x="{X(i) + 9:.1f}" y="{Y(v) + 4:.1f}" class="lbl">{v} %</text>')
    s.append("</svg>")
    return Markup("".join(s))


tpl.env.filters["date"] = fmt_date
tpl.env.filters["delta"] = fmt_delta
tpl.env.globals.update(linechart=linechart, intervals=measure.INTERVALS, demo=config.demo_mode,
                       pct=report.pct, channel_label=config.CHANNEL_LABEL, version=__version__)


def get_site(site_id):
    s = db.one("SELECT * FROM sites WHERE id=? AND tenant_id=?", (site_id, TENANT))
    if not s:
        raise HTTPException(404, "Website nicht gefunden")
    s["aliases_list"] = db.jload(s["aliases"], [])
    s["profile_data"] = db.jload(s["profile"], {}) or {}
    return s


def get_run(run_id):
    r = db.one("SELECT r.* FROM runs r JOIN sites s ON s.id=r.site_id WHERE r.id=? AND s.tenant_id=?", (run_id, TENANT))
    if not r:
        raise HTTPException(404, "Lauf nicht gefunden")
    return r


def quick(run_id):
    """Kennzahlen eines Laufs für Listen."""
    r = db.one("SELECT SUM(CASE WHEN channel!='web' THEN mentioned END) AS h, "
               "SUM(CASE WHEN channel!='web' THEN 1 END) AS t, "
               "SUM(CASE WHEN channel='web' THEN mentioned END) AS wh, SUM(CASE WHEN channel='web' THEN 1 END) AS wt "
               "FROM answers WHERE run_id=? AND status='ok'", (run_id,))
    return {"ai": report.pct(r["h"] or 0, r["t"] or 0), "h": r["h"] or 0, "t": r["t"] or 0,
            "web": f"{r['wh'] or 0}/{r['wt'] or 0}" if r["wt"] else "–"}


def back(request, default="/"):
    return RedirectResponse(request.headers.get("referer") or default, 303)


# ---------- Websites ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    sites = db.q("SELECT * FROM sites WHERE tenant_id=? ORDER BY name COLLATE NOCASE", (TENANT,))
    for s in sites:
        runs = db.q("SELECT * FROM runs WHERE site_id=? AND status='done' ORDER BY id DESC LIMIT 2", (s["id"],))
        s["last"] = runs[0] if runs else None
        s["k"] = quick(runs[0]["id"]) if runs else None
        s["dlt"] = (s["k"]["ai"] - quick(runs[1]["id"])["ai"]) if len(runs) > 1 and s["k"]["ai"] is not None else None
        s["open"] = db.one("SELECT * FROM runs WHERE site_id=? AND status IN ('queued','running')", (s["id"],))
    month = db.now()[:7]
    usage = db.one("SELECT COUNT(*) AS n, COUNT(DISTINCT site_id) AS s FROM runs WHERE status='done' AND started_at LIKE ?", (month + "%",))
    missing = [config.CHANNEL_LABEL[k] for k, v in config.channel_status().items() if not v[0]]
    return tpl.TemplateResponse(request, "sites.html", {"sites": sites, "usage": usage, "missing": missing})


@app.post("/sites")
def site_create(request: Request, url: str = Form(...), name: str = Form(""), interval: str = Form("monthly"),
                auto_start: str = Form("")):
    try:
        sid = questions.create_site(url, name, interval, bool(auto_start), TENANT)
    except ValueError as e:
        raise HTTPException(400, str(e))
    threading.Thread(target=questions.analyse_site, args=(sid,), daemon=True).start()
    return RedirectResponse(f"/sites/{sid}", 303)


@app.get("/sites/{sid}", response_class=HTMLResponse)
def site_page(request: Request, sid: int):
    s = get_site(sid)
    runs = db.q("SELECT * FROM runs WHERE site_id=? ORDER BY id DESC", (sid,))
    for r in runs:
        r["k"] = quick(r["id"]) if r["status"] == "done" else None
    nq = db.one("SELECT COUNT(*) AS n FROM questions WHERE site_id=? AND active=1", (sid,))["n"]
    status = config.channel_status()
    return tpl.TemplateResponse(request, "site.html", {
        "s": s, "runs": runs, "nq": nq, "tab": "overview",
        "missing": [config.CHANNEL_LABEL[k] for k, v in status.items() if not v[0]]})


@app.post("/sites/{sid}/settings")
def site_settings(request: Request, sid: int, name: str = Form(...), interval: str = Form(...), aliases: str = Form("")):
    s = get_site(sid)
    al = [a.strip() for a in aliases.replace("\n", ",").split(",") if a.strip()]
    nxt = s["next_run_at"]
    if interval != s["interval"]:
        last = db.one("SELECT started_at FROM runs WHERE site_id=? AND status='done' ORDER BY id DESC LIMIT 1", (sid,))
        nxt = measure.next_run(interval, last["started_at"]) if last else None
    db.x("UPDATE sites SET name=?, interval=?, aliases=?, next_run_at=? WHERE id=?",
         (name.strip() or s["name"], interval if interval in measure.INTERVALS else "monthly",
          json.dumps(al, ensure_ascii=False), nxt, sid))
    if al != s["aliases_list"]:
        measure.recompute_mentions(sid)
    return back(request)


@app.post("/sites/{sid}/run")
def site_run(sid: int):
    get_site(sid)
    return RedirectResponse(f"/runs/{measure.enqueue(sid)}", 303)


@app.post("/sites/{sid}/reanalyse")
def site_reanalyse(sid: int):
    get_site(sid)
    if db.one("SELECT 1 AS x FROM runs WHERE site_id=?", (sid,)):
        raise HTTPException(400, "Nach der ersten Messung bleibt der Fragenkatalog bestehen")
    db.x("UPDATE sites SET state='analysing', state_msg='' WHERE id=?", (sid,))
    threading.Thread(target=questions.analyse_site, args=(sid,), daemon=True).start()
    return RedirectResponse(f"/sites/{sid}", 303)


@app.post("/sites/{sid}/delete")
def site_delete(sid: int):
    get_site(sid)
    for r in db.q("SELECT id FROM runs WHERE site_id=?", (sid,)):
        db.x("DELETE FROM answer_vendors WHERE answer_id IN (SELECT id FROM answers WHERE run_id=?)", (r["id"],))
        for t in ("answers", "run_questions", "recommendations"):
            db.x(f"DELETE FROM {t} WHERE run_id=?", (r["id"],))
    for t in ("runs", "questions", "topics", "vendors", "changes"):
        db.x(f"DELETE FROM {t} WHERE site_id=?", (sid,))
    db.x("DELETE FROM sites WHERE id=?", (sid,))
    return RedirectResponse("/", 303)


# ---------- Fragen und Themenfelder ----------

@app.get("/sites/{sid}/questions", response_class=HTMLResponse)
def questions_page(request: Request, sid: int):
    s = get_site(sid)
    topics = questions.topics(sid)
    for t in topics:
        t["questions"] = db.q("SELECT * FROM questions WHERE topic_id=? AND active=1 ORDER BY id", (t["id"],))
    measured = bool(db.one("SELECT 1 AS x FROM runs WHERE site_id=? AND status='done'", (sid,)))
    return tpl.TemplateResponse(request, "questions.html", {
        "s": s, "topics": topics, "measured": measured, "tab": "questions",
        "nq": sum(len(t["questions"]) for t in topics)})


def _own_question(qid):
    qu = db.one("SELECT * FROM questions WHERE id=?", (qid,))
    if not qu:
        raise HTTPException(404)
    get_site(qu["site_id"])
    return qu


def _own_topic(tid):
    t = db.one("SELECT * FROM topics WHERE id=?", (tid,))
    if not t:
        raise HTTPException(404)
    get_site(t["site_id"])
    return t


@app.post("/sites/{sid}/questions")
def question_add(request: Request, sid: int, text: str = Form(...), topic_id: str = Form(""), is_brand: str = Form("")):
    get_site(sid)
    if text.strip():
        if topic_id:
            _own_topic(int(topic_id))
        questions.add_question(sid, text, int(topic_id) if topic_id else None, 1 if is_brand else 0)
    return back(request)


@app.post("/questions/{qid}")
def question_update(request: Request, qid: int, text: str = Form(...), topic_id: int = Form(...)):
    _own_question(qid)
    _own_topic(topic_id)
    questions.update_question(qid, text, topic_id)
    return back(request)


@app.post("/questions/{qid}/delete")
def question_delete(request: Request, qid: int):
    _own_question(qid)
    questions.remove_question(qid)
    return back(request)


@app.post("/sites/{sid}/topics")
def topic_add(request: Request, sid: int, name: str = Form(...)):
    get_site(sid)
    if name.strip():
        questions.add_topic(sid, name)
    return back(request)


@app.post("/topics/{tid}")
def topic_update(request: Request, tid: int, name: str = Form(...), merge_into: str = Form("")):
    _own_topic(tid)
    questions.rename_topic(tid, name)
    if merge_into:
        _own_topic(int(merge_into))
        questions.merge_topics(tid, int(merge_into))
    return back(request)


# ---------- Anbieter ----------

@app.get("/sites/{sid}/vendors", response_class=HTMLResponse)
def vendors_page(request: Request, sid: int):
    s = get_site(sid)
    rows = db.q("SELECT v.*, (SELECT COUNT(*) FROM answer_vendors av WHERE av.vendor_id=v.id) AS n "
                "FROM vendors v WHERE v.site_id=? ORDER BY v.hidden, n DESC, v.name", (sid,))
    by_id = {v["id"]: v for v in rows}
    for v in rows:
        if v["merged_into"] and v["merged_into"] in by_id:
            by_id[v["merged_into"]].setdefault("aliases", []).append(v["name"])
            by_id[v["merged_into"]]["n"] += v["n"]
    main = sorted([v for v in rows if not v["merged_into"]], key=lambda v: (v["hidden"], -v["n"], v["name"]))
    return tpl.TemplateResponse(request, "vendors.html", {"s": s, "vendors": main, "tab": "vendors"})


@app.post("/vendors/{vid}")
def vendor_update(request: Request, vid: int, action: str = Form(...), name: str = Form(""), target: str = Form("")):
    v = db.one("SELECT * FROM vendors WHERE id=?", (vid,))
    if not v:
        raise HTTPException(404)
    s = get_site(v["site_id"])
    if action == "rename" and name.strip():
        db.x("UPDATE vendors SET name=? WHERE id=?", (name.strip()[:80], vid))
    elif action in ("hide", "show"):
        db.x("UPDATE vendors SET hidden=? WHERE id=?", (1 if action == "hide" else 0, vid))
    elif action == "merge" and target and int(target) != vid:
        t = db.one("SELECT * FROM vendors WHERE id=? AND site_id=?", (int(target), s["id"]))
        if t:
            db.x("UPDATE vendors SET merged_into=? WHERE id=? OR merged_into=?", (t["id"], vid, vid))
    elif action == "unmerge":
        db.x("UPDATE vendors SET merged_into=NULL WHERE merged_into=?", (vid,))
    elif action == "own":
        # Der Eintrag ist eine Schreibweise der eigenen Marke: aufnehmen, ausblenden, Treffer neu bestimmen.
        al = s["aliases_list"] + [v["name"]]
        db.x("UPDATE sites SET aliases=? WHERE id=?", (json.dumps(al, ensure_ascii=False), s["id"]))
        db.x("UPDATE vendors SET hidden=1 WHERE id=?", (vid,))
        measure.recompute_mentions(s["id"])
    return back(request)


# ---------- Läufe und Berichte ----------

@app.get("/runs/{rid}", response_class=HTMLResponse)
def run_page(request: Request, rid: int):
    r = get_run(rid)
    if r["status"] == "done":
        return RedirectResponse(f"/runs/{rid}/report", 303)
    return tpl.TemplateResponse(request, "run.html", {"r": r, "s": get_site(r["site_id"])})


@app.get("/api/runs/{rid}")
def run_status(rid: int):
    r = get_run(rid)
    return {k: r[k] for k in ("status", "progress", "step", "error")}


@app.get("/api/sites/{sid}")
def site_status(sid: int):
    return {"state": get_site(sid)["state"]}


@app.post("/runs/{rid}/retry")
def run_retry(rid: int):
    get_run(rid)
    measure.retry_failed(rid)
    return RedirectResponse(f"/runs/{rid}", 303)


def render_report(request, rid, pdf=False):
    r = get_run(rid)
    if r["status"] != "done":
        raise HTTPException(409, "Der Lauf ist noch nicht abgeschlossen")
    css = (BASE / "static" / "report.css").read_text(encoding="utf-8")
    return tpl.get_template("report.html").render(request=request, R=report.build(rid), css=Markup(css), pdf=pdf)


@app.get("/runs/{rid}/report", response_class=HTMLResponse)
def run_report(request: Request, rid: int):
    return HTMLResponse(render_report(request, rid))


@app.get("/runs/{rid}/report.pdf")
def run_report_pdf(request: Request, rid: int):
    html = render_report(request, rid, pdf=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise HTTPException(501, "Für den PDF-Export bitte 'pip install playwright' und 'playwright install chromium' "
                                 "ausführen. Alternativ den Bericht im Browser über Drucken als PDF speichern.")
    out = {}

    def make():  # eigener Thread: Playwright verträgt keine laufende Ereignisschleife
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=env("CHROMIUM_PATH") or None)
            page = b.new_page()
            page.set_content(html, wait_until="load")
            out["pdf"] = page.pdf(format="A4", print_background=True,
                                  margin={"top": "16mm", "bottom": "16mm", "left": "15mm", "right": "15mm"})
            b.close()

    t = threading.Thread(target=make)
    t.start()
    t.join()
    if "pdf" not in out:
        raise HTTPException(500, "PDF konnte nicht erzeugt werden")
    R = get_run(rid)
    fname = f"AI-Visibility-{get_site(R['site_id'])['domain']}-{(R['started_at'] or '')[:10]}.pdf"
    return Response(out["pdf"], media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{fname}"'})


@app.get("/answers/{aid}", response_class=HTMLResponse)
def answer_page(request: Request, aid: int):
    a = db.one("SELECT * FROM answers WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404)
    r = get_run(a["run_id"])
    qu = db.one("SELECT * FROM run_questions WHERE run_id=? AND question_id=?", (a["run_id"], a["question_id"]))
    vmap = report.vendor_map(r["site_id"])
    vs = [vmap[x["vendor_id"]]["name"] for x in db.q("SELECT * FROM answer_vendors WHERE answer_id=? ORDER BY pos", (aid,))
          if x["vendor_id"] in vmap]
    return tpl.TemplateResponse(request, "answer.html", {
        "a": a, "r": r, "q": qu, "s": get_site(r["site_id"]), "cites": db.jload(a["citations"], []), "vendors": vs})


# ---------- Einstellungen ----------

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return tpl.TemplateResponse(request, "settings.html", {
        "status": config.channel_status(), "channels": config.CHANNELS,
        "analysis": config.analysis_provider(), "tab": "settings"})


@app.post("/api/channels/{key}/test")
def channel_test(key: str):
    if key not in config.CHANNEL_LABEL:
        raise HTTPException(404)
    qu = {"text": "Welche Anbieter für Projektmanagement-Software gibt es in Deutschland?", "lang": "de",
          "question_id": 0, "revision": 1, "topic_id": 0, "is_brand": 0}
    try:
        res = channels.ask(key, qu, {"site": {"id": 0, "name": "Test", "url": "https://example.org", "domain": "example.org"}, "run_seq": 0})
        return {"ok": True, "text": res["text"][:400], "citations": len(res["citations"])}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:400]})
