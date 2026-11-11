"""Bericht berechnen: Trefferquoten, Anbieteranteile, Veränderung zur Vorprüfung, Verläufe.

Alles wird beim Aufruf aus den gespeicherten Antworten gerechnet. Bereinigt der Nutzer später die
Anbieterliste oder legt Themenfelder zusammen, gilt das dadurch einheitlich für alle Läufe.
"""
from collections import Counter, defaultdict

from . import config, db
from .textutil import domain_of, same_site

def is_ai(channel):
    """Alle Kanäle außer der Websuche sind KI-Kanäle, auch inzwischen entfernte OpenRouter-Modelle."""
    return channel != "web"


def channel_list(runs):
    """Kanäle der Läufe in Berichtsreihenfolge, so wie sie beim Lauf eingestellt waren.

    Ein später entferntes OpenRouter-Modell bleibt dadurch in alten Berichten und Verläufen erhalten;
    ein neu gewähltes erscheint erst ab dem Lauf, in dem es gemessen wurde.
    """
    labels = {}
    for r in runs:
        for k, v in (db.jload(r["channels"], {}) or {}).items():
            labels.setdefault(k, (v or {}).get("label") or config.CHANNEL_LABEL.get(k, k))
    if not labels:
        return list(config.CHANNELS)
    order = [c["key"] for c in config.CHANNELS]
    rank = lambda k: order.index(k) if k in order else order.index("web") - 0.5  # noqa: E731
    return [{"key": k, "label": labels[k], "kind": "ai" if is_ai(k) else "web"} for k in sorted(labels, key=rank)]


def pct(h, t):
    return round(100 * h / t) if t else None


def topic_map(site_id):
    """topic_id -> aktuelles Themenfeld (zusammengelegte Felder zeigen auf ihr Ziel)."""
    rows = {t["id"]: t for t in db.q("SELECT * FROM topics WHERE site_id=?", (site_id,))}
    out = {}
    for tid, t in rows.items():
        seen = set()
        while t["merged_into"] and t["merged_into"] in rows and t["id"] not in seen:
            seen.add(t["id"])
            t = rows[t["merged_into"]]
        out[tid] = t
    return out


def vendor_map(site_id):
    rows = {v["id"]: v for v in db.q("SELECT * FROM vendors WHERE site_id=?", (site_id,))}
    out = {}
    for vid, v in rows.items():
        seen = set()
        while v["merged_into"] and v["merged_into"] in rows and v["id"] not in seen:
            seen.add(v["id"])
            v = rows[v["merged_into"]]
        out[vid] = v
    return out


def run_stats(run, tmap, vmap):
    """Kennzahlen eines Laufs."""
    rq = db.q("SELECT * FROM run_questions WHERE run_id=?", (run["id"],))
    answers = db.q("SELECT * FROM answers WHERE run_id=?", (run["id"],))
    av = defaultdict(list)
    for r in db.q("SELECT av.* FROM answer_vendors av JOIN answers a ON a.id=av.answer_id WHERE a.run_id=?", (run["id"],)):
        v = vmap.get(r["vendor_id"])
        if v and not v["hidden"]:
            av[r["answer_id"]].append(v["id"])
    by_q = defaultdict(dict)
    for a in answers:
        by_q[a["question_id"]][a["channel"]] = a
    measured = {a["channel"] for a in answers if a["status"] == "ok"}
    qs = []
    for r in rq:
        t = tmap.get(r["topic_id"])
        cells = by_q.get(r["question_id"], {})
        ok_ai = [a for ch, a in cells.items() if is_ai(ch) and a["status"] == "ok"]
        web = cells.get("web")
        qs.append({**r, "tid": t["id"] if t else r["topic_id"], "topic": t["name"] if t else r["topic_name"],
                   "cells": cells, "ai_hits": sum(a["mentioned"] for a in ok_ai), "ai_total": len(ok_ai),
                   "web_ok": bool(web and web["status"] == "ok"), "web_rank": web["rank"] if web else None,
                   "vendors": {a["id"]: set(av.get(a["id"], [])) for a in ok_ai if a["vendors_done"]}})
    qs.sort(key=lambda x: (x["is_brand"], x["topic"], int(x["code"][1:]) if x["code"][1:].isdigit() else 0))
    return {"run": run, "questions": qs, "measured": measured,
            "errors": Counter(a["channel"] for a in answers if a["status"] == "error")}


def agg(qs, channel=None):
    """(Treffer, Antworten) über die KI-Kanäle bzw. einen Kanal."""
    h = t = 0
    for qu in qs:
        for ch, a in qu["cells"].items():
            if (ch == channel if channel else is_ai(ch)) and a["status"] == "ok":
                t += 1
                h += 1 if a["mentioned"] else 0
    return h, t


def web_agg(qs):
    ok = [qu for qu in qs if qu["web_ok"]]
    return sum(1 for qu in ok if qu["web_rank"]), len(ok)


def delta(cur, prev):
    """Veränderung in Prozentpunkten; None, wenn eine Seite fehlt."""
    a, b = pct(*cur), pct(*prev) if prev else None
    return None if a is None or b is None else a - b


def vendor_shares(qs):
    """-> {topic_id: {"n": Antworten, "self": Nennungen eigene Marke, "v": Counter(vendor_id)}}"""
    out = {}
    for qu in qs:
        if qu["is_brand"]:
            continue
        d = out.setdefault(qu["tid"], {"n": 0, "self": 0, "v": Counter(), "name": qu["topic"]})
        for ch, a in qu["cells"].items():
            if is_ai(ch) and a["status"] == "ok" and a["id"] in qu["vendors"]:
                d["n"] += 1
                d["self"] += 1 if a["mentioned"] else 0
                d["v"].update(qu["vendors"][a["id"]])
    return out


def build(run_id):
    run = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    site = db.one("SELECT * FROM sites WHERE id=?", (run["site_id"],))
    site["aliases_list"] = db.jload(site["aliases"], [])
    tmap, vmap = topic_map(site["id"]), vendor_map(site["id"])
    history = db.q("SELECT * FROM runs WHERE site_id=? AND mode=? AND id<=? AND (status='done' OR id=?) ORDER BY id",
                   (site["id"], run["mode"], run_id, run_id))
    stats = [run_stats(r, tmap, vmap) for r in history]
    cur, prev = stats[-1], (stats[-2] if len(stats) > 1 else None)
    qs = cur["questions"]
    nb = [qu for qu in qs if not qu["is_brand"]]
    brand = [qu for qu in qs if qu["is_brand"]]

    # --- Vergleichbare Basis: Fragen, die in beiden Läufen im selben Wortlaut gestellt wurden
    prev_q = {qu["question_id"]: qu for qu in prev["questions"]} if prev else {}
    comparable = {qu["question_id"] for qu in qs if qu["question_id"] in prev_q
                  and prev_q[qu["question_id"]]["revision"] == qu["revision"]}
    cmp_cur = [qu for qu in qs if qu["question_id"] in comparable]
    cmp_prev = [qu for qu in prev["questions"] if qu["question_id"] in comparable] if prev else []
    for qu in qs:
        p = prev_q.get(qu["question_id"])
        qu["flag"] = None if not prev else ("neu" if not p else ("neustart" if p["revision"] != qu["revision"] else None))
        qu["prev_hits"] = f"{p['ai_hits']}/{p['ai_total']}" if p and not qu["flag"] else None
        qu["moved_from"] = p["topic"] if p and p["tid"] != qu["tid"] else None
    removed = [p for qid, p in prev_q.items() if qid not in {qu["question_id"] for qu in qs}]

    def d(filt=lambda qu: True, channel=None, web=False):
        if not prev:
            return None
        a, b = [qu for qu in cmp_cur if filt(qu)], [qu for qu in cmp_prev if filt(qu)]
        return delta(web_agg(a), web_agg(b)) if web else delta(agg(a, channel), agg(b, channel))

    head = {"ai": agg(qs), "nb": agg(nb), "brand": agg(brand), "web": web_agg(qs),
            "d_ai": d(), "d_nb": d(lambda qu: not qu["is_brand"]), "d_web": d(web=True),
            "comparable": len(comparable), "questions": len(qs)}

    channels = channel_list([run])
    models = []
    for c in channels:
        k = c["key"]
        if c["kind"] == "ai":
            h, t = agg(qs, k)
            hn, tn = agg(nb, k)
            top = Counter()
            cites = 0
            for qu in nb:
                a = qu["cells"].get(k)
                if a and a["status"] == "ok":
                    cites += a["cited"]
                    top.update(qu["vendors"].get(a["id"], ()))
            models.append({**c, "hits": h, "total": t, "hits_nb": hn, "total_nb": tn, "rate": pct(h, t),
                           "delta": d(channel=k), "measured": k in cur["measured"], "cites_own": cites,
                           "errors": cur["errors"].get(k, 0),
                           "top": [vmap[v]["name"] for v, _ in top.most_common(3)]})
        else:
            h, t = web_agg(qs)
            models.append({**c, "hits": h, "total": t, "rate": pct(h, t), "delta": d(web=True),
                           "measured": k in cur["measured"], "errors": cur["errors"].get(k, 0), "top": []})

    # --- Themenfelder
    changes = []
    if prev:
        changes = db.q("SELECT * FROM changes WHERE site_id=? AND id>? AND id<=? ORDER BY id",
                       (site["id"], prev["run"]["change_mark"] or 0, run["change_mark"] or 0))
        for ch in changes:
            ch["detail"] = db.jload(ch["detail"], {})
    topic_notes = defaultdict(list)
    for ch in changes:
        dt, kind = ch["detail"], ch["kind"]
        tid = tmap[ch["topic_id"]]["id"] if ch["topic_id"] in tmap else ch["topic_id"]
        if kind == "topic_renamed":
            topic_notes[tid].append(f"umbenannt (vorher „{dt.get('old')}“)")
        elif kind == "topic_merged":
            topic_notes[tid].append(f"mit „{dt.get('old')}“ zusammengelegt")
        elif kind == "topic_added":
            topic_notes[tid].append("neu angelegt")
        elif kind == "question_moved":
            topic_notes[tid].append("Frage hinzugekommen (verschoben)")
            old = dt.get("old_topic_id")
            if old in tmap:
                topic_notes[tmap[old]["id"]].append("Frage abgegeben (verschoben)")
        elif kind == "question_added":
            topic_notes[tid].append("neue Frage")
        elif kind == "question_removed":
            topic_notes[tid].append("Frage gestrichen")
        elif kind == "question_edited":
            topic_notes[tid].append("Frage geändert")
    topics = []
    order = []
    for qu in qs:
        if qu["tid"] not in order:
            order.append(qu["tid"])
    for tid in order:
        tq = [qu for qu in qs if qu["tid"] == tid]
        ptq = [qu for qu in prev["questions"] if qu["tid"] == tid] if prev else []
        h, t = agg(tq)
        notes = list(dict.fromkeys(topic_notes.get(tid, [])))
        topics.append({"id": tid, "name": tq[0]["topic"], "is_brand": all(qu["is_brand"] for qu in tq),
                       "hits": h, "total": t, "rate": pct(h, t), "count": len(tq),
                       "delta": delta((h, t), agg(ptq)) if ptq else None, "notes": notes,
                       "web": web_agg(tq)})

    # --- Anbieteranteile je Themenfeld
    sh, psh = vendor_shares(qs), (vendor_shares(prev["questions"]) if prev else {})
    vt = [t for t in topics if t["id"] in sh and sh[t["id"]]["n"]]
    totals = Counter()
    for t in vt:
        totals.update(sh[t["id"]]["v"])
    n_all = sum(sh[t["id"]]["n"] for t in vt)
    shown = [v for v, n in totals.most_common(12) if n >= 2] or [v for v, _ in totals.most_common(8)]

    def cell(tid, vid):
        s, p = sh[tid], psh.get(tid)
        c_ = s["self"] if vid == "self" else s["v"].get(vid, 0)
        share = pct(c_, s["n"])
        pshare = pct(p["self"] if vid == "self" else p["v"].get(vid, 0), p["n"]) if p and p["n"] else None
        return {"share": share, "count": c_, "delta": None if pshare is None else share - pshare}

    self_total = sum(sh[t["id"]]["self"] for t in vt)
    vendor_rows = [{"name": site["name"], "self": True, "total": self_total, "share": pct(self_total, n_all),
                    "cells": [cell(t["id"], "self") for t in vt]}]
    for vid in shown:
        vendor_rows.append({"name": vmap[vid]["name"], "self": False, "total": totals[vid],
                            "share": pct(totals[vid], n_all), "cells": [cell(t["id"], vid) for t in vt]})
    ranking = sorted(vendor_rows, key=lambda r: -r["total"])[:10]
    vendors = {"topics": [{"id": t["id"], "name": t["name"], "n": sh[t["id"]]["n"], "notes": t["notes"]} for t in vt],
               "rows": vendor_rows, "ranking": ranking, "n": n_all,
               "analysed": n_all > 0, "others": max(0, len(totals) - len(shown))}

    # --- Quellen, auf die sich die Antworten stützen
    src, src_hit, n_src = Counter(), Counter(), 0
    for qu in nb:
        for ch, a in qu["cells"].items():
            if is_ai(ch) and a["status"] == "ok":
                doms = {domain_of(u) for u in db.jload(a["citations"], [])} - {""}
                n_src += 1 if doms else 0
                src.update(doms)
                if a["mentioned"]:
                    src_hit.update(doms)
    sources = [{"domain": dm, "count": n, "with_us": src_hit[dm], "own": same_site(dm, site["domain"])}
               for dm, n in src.most_common(12)]

    # --- Technik mit Veränderung
    audit = db.jload(run["audit"], {}) or {}
    prev_checks = {c["key"]: c for c in (db.jload(prev["run"]["audit"], {}) or {}).get("checks", [])} if prev else {}
    for c in audit.get("checks", []):
        p = prev_checks.get(c["key"])
        c["prev"] = p["status"] if p and p["status"] != c["status"] else None

    # --- Verläufe über alle Läufe
    def series(fn):
        return [fn(s) for s in stats]

    trend_topics = []
    for t in topics:
        vals = series(lambda s, tid=t["id"]: pct(*agg([qu for qu in s["questions"] if qu["tid"] == tid])))
        trend_topics.append({"name": t["name"], "values": vals})
    sets = [frozenset((qu["question_id"], qu["revision"]) for qu in s["questions"]) for s in stats]
    trends = {
        "labels": [s["run"]["started_at"][:10] for s in stats],
        "changed": [i > 0 and sets[i] != sets[i - 1] for i in range(len(stats))],
        "overall": series(lambda s: pct(*agg(s["questions"]))),
        "nb": series(lambda s: pct(*agg([qu for qu in s["questions"] if not qu["is_brand"]]))),
        "channels": [{"label": c["label"], "values": series(
            lambda s, k=c["key"], w=c["kind"] == "web": pct(*(web_agg(s["questions"]) if w else agg(s["questions"], k))))}
            for c in channel_list(history)],
        "topics": trend_topics,
    }

    labels = {"question_added": "Frage ergänzt", "question_removed": "Frage gestrichen",
              "question_edited": "Frage geändert – Verlauf beginnt neu", "question_moved": "Frage verschoben",
              "topic_renamed": "Themenfeld umbenannt", "topic_merged": "Themenfelder zusammengelegt",
              "topic_added": "Themenfeld angelegt"}
    change_rows = []
    for ch in changes:
        dt = ch["detail"]
        txt = {"question_added": f"„{dt.get('text')}“ in „{dt.get('topic')}“",
               "question_removed": f"„{dt.get('text')}“",
               "question_edited": f"vorher: „{dt.get('old')}“ · jetzt: „{dt.get('new')}“",
               "question_moved": f"„{dt.get('text')}“ von „{dt.get('old_topic')}“ nach „{dt.get('new_topic')}“",
               "topic_renamed": f"„{dt.get('old')}“ heißt jetzt „{dt.get('new')}“",
               "topic_merged": f"„{dt.get('old')}“ ist in „{dt.get('new')}“ aufgegangen",
               "topic_added": f"„{dt.get('name')}“"}.get(ch["kind"], "")
        change_rows.append({"at": ch["at"][:10], "label": labels.get(ch["kind"], ch["kind"]), "text": txt})

    seq = len(history)
    return {
        "site": site, "run": run, "prev": prev["run"] if prev else None, "seq": seq,
        "ref": f"P-{(run['started_at'] or run['queued_at'])[:4]}-{site['id']:03d}-{seq:02d}",
        "date": (run["started_at"] or run["queued_at"])[:10], "demo": run["mode"] == "demo",
        "head": head, "models": models, "ai_models": [m for m in models if m["kind"] == "ai"],
        "questions": qs, "removed": removed, "topics": topics, "vendors": vendors, "sources": sources,
        "n_src": n_src, "checks": audit.get("checks", []), "pages": audit.get("pages", 0),
        "recs": db.q("SELECT * FROM recommendations WHERE run_id=? ORDER BY prio", (run_id,)),
        "findings": (db.jload(run["summary"], {}) or {}).get("findings", []),
        "trends": trends, "changes": change_rows, "channels": channels,
        "unmeasured": [m["label"] for m in models if not m["measured"]],
        "errors": sum(cur["errors"].values()),
    }
