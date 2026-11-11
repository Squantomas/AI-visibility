"""Fragen und Themenfelder: aus dem Website-Inhalt ableiten und später pflegen.

Jede Änderung wird protokolliert (Tabelle changes), damit der nächste Bericht sie kennzeichnen kann.
"""
import json
import re
from urllib.parse import urlparse

from . import config, crawl, db, llm
from .textutil import default_aliases, domain_of, fold, words

BRAND_TOPIC = "Marke"

SYSTEM = """Du bist Marktanalyst mit Vertriebserfahrung. Du liest den Inhalt einer Unternehmens-Website und
leitest daraus die Fragen ab, die ein künftiger Kunde einem KI-Assistenten stellen würde, BEVOR er einen
bestimmten Anbieter kennt. Du erfindest keine Fakten über das Unternehmen."""

PROMPT = """Website: {url}

Inhalt der wichtigsten Seiten:
{content}

Aufgabe:
1. Bestimme Unternehmensname, gängige Schreibweisen der Marke (z. B. mit und ohne Umlaut, Kurzform) und die
   Hauptsprache der Website ("de" oder "en").
2. Bilde 3 bis 5 Themenfelder nach den Angebotsbereichen der Website. Namen kurz (1 bis 3 Wörter).
3. Formuliere insgesamt etwa 18 Fragen, 3 bis 6 je Themenfeld, so wie Einkäufer, Fachleute oder
   Entscheider sie einem KI-Assistenten stellen würden:
   - Die Fragen nennen das Unternehmen NICHT beim Namen.
   - Jede Frage zielt darauf, dass Anbieter genannt werden ("Welche Hersteller ...", "Wer liefert ...",
     "Wir suchen einen Partner für ... Wer kommt infrage?").
   - Mische Suchfragen, problemgetriebene Fragen und, falls die Website einen regionalen Schwerpunkt zeigt,
     regionale Fragen.
   - Schreibe in der Hauptsprache der Website. Hat die Website eine englische Fassung oder internationales
     Geschäft, formuliere ein bis zwei Fragen auf Englisch.
4. Formuliere genau 2 Markenfragen, die das Unternehmen beim Namen nennen (was es macht, was es anbietet).

Antwortformat (JSON):
{{"company": "...", "aliases": ["..."], "language": "de", "summary": "ein bis zwei Sätze zum Angebot",
  "topics": [{{"name": "...", "questions": [{{"text": "...", "lang": "de"}}]}}],
  "brand_questions": [{{"text": "...", "lang": "de"}}]}}"""


def guess_lang(text, default="de"):
    en = len(re.findall(r"\b(which|what|who|where|how|the|for|are|is|and|suppliers?|companies)\b", text.lower()))
    de = len(re.findall(r"\b(welche[rs]?|wer|was|wie|wo|für|und|gibt|wir|der|die|das|anbieter)\b", text.lower()))
    return "en" if en > de else ("de" if de > en else default)


def propose(site, data):
    """Vorschlag für Fragen und Themenfelder. Mit Auswertungsmodell per KI, sonst einfache Heuristik."""
    provider = config.analysis_provider()
    if provider and not config.demo_mode():
        try:
            res = llm.analyse(provider, SYSTEM, PROMPT.format(url=site["url"], content=crawl.content_excerpt(data)))
            if res.get("topics"):
                res["method"] = "ki"
                return res
        except Exception as e:
            fallback = heuristic(site, data)
            fallback["note"] = f"KI-Analyse fehlgeschlagen ({str(e)[:120]}); einfache Ableitung verwendet."
            return fallback
    return heuristic(site, data)


def heuristic(site, data):
    """Ableitung ohne KI: Themen aus Seitenüberschriften, Fragen aus Vorlagen. Für Demo und Notfall."""
    pages = data.get("pages", [])
    home = pages[0] if pages else {"title": "", "lang": "de"}
    name = site["name"] or re.split(r"\s[|–\-:·]\s", home["title"])[-1].strip()
    if len(name) < 4 or fold(name) in ("start", "home", "startseite", "willkommen", "homepage"):
        name = site["domain"].split(".")[0].capitalize()
    brand = fold(name)
    groups = {}
    for p in pages[1:]:
        label = (p["h1"][0] if p["h1"] else re.split(r"\s[|–\-:·]\s", p["title"])[0]).strip()
        if not (3 < len(label) < 60) or brand in fold(label):
            continue
        if re.search(r"impressum|datenschutz|kontakt|agb|karriere|jobs|news|aktuelles|privacy|imprint|contact", fold(label + p["url"])):
            continue
        seg = [s for s in urlparse(p["url"]).path.split("/") if s and len(s) > 2]
        topic = seg[0].replace("-", " ").title() if len(seg) > 1 else "Angebot"
        groups.setdefault(topic, [])
        if label not in groups[topic]:
            groups[topic].append(label)
    if not groups:
        groups = {"Angebot": [h for h in home.get("h2", []) if 3 < len(h) < 60][:6] or ["das Angebot dieser Branche"]}
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    top, rest = ranked[:4], [l for _, ls in ranked[4:] for l in ls]
    if rest:
        top.append(("Weitere Themen", rest))
    templates = ["Welche Anbieter gibt es für {x}?", "Wer bietet {x} an?",
                 "Wir suchen einen Partner für {x}. Wer kommt infrage?",
                 "Welche Unternehmen sind auf {x} spezialisiert?"]
    topics, i = [], 0
    per = max(2, 18 // max(1, len(top)))
    for tname, labels in top:
        qs = []
        for label in labels[:per]:
            qs.append({"text": templates[i % 4].format(x=label), "lang": "de"})
            i += 1
        topics.append({"name": tname, "questions": qs})
    return {"company": name, "aliases": [], "language": home.get("lang") or "de", "summary": "",
            "topics": topics, "method": "einfach",
            "brand_questions": [{"text": f"Was macht {name}?", "lang": "de"},
                                {"text": f"Welche Leistungen bietet {name} an?", "lang": "de"}]}


def analyse_site(site_id):
    """Website einlesen und Fragenvorschlag speichern. Läuft im Hintergrund."""
    site = db.one("SELECT * FROM sites WHERE id=?", (site_id,))
    try:
        data = crawl.crawl(site["url"], max_pages=40)
        if not data["pages"]:
            raise RuntimeError("; ".join(data["errors"]) or "Website nicht erreichbar")
        res = propose(site, data)
        db.x("DELETE FROM questions WHERE site_id=?", (site_id,))  # falls ein früherer Versuch abgebrochen ist
        db.x("DELETE FROM topics WHERE site_id=?", (site_id,))
        name = site["name"] or res.get("company") or site["domain"]
        aliases = list(dict.fromkeys(default_aliases(name, site["domain"]) + [a for a in res.get("aliases", []) if a]))
        profile = {"summary": res.get("summary", ""), "method": res.get("method", ""), "note": res.get("note", "")}
        db.x("UPDATE sites SET name=?, aliases=?, language=?, profile=? WHERE id=?",
             (name, json.dumps(aliases, ensure_ascii=False), res.get("language") or "de",
              json.dumps(profile, ensure_ascii=False), site_id))
        for pos, t in enumerate(res["topics"]):
            tid = db.x("INSERT INTO topics (site_id, name, position, created_at) VALUES (?,?,?,?)",
                       (site_id, t["name"][:60], pos, db.now()))
            for qu in t.get("questions", []):
                _insert_question(site_id, tid, qu["text"], qu.get("lang") or "de", 0)
        if res.get("brand_questions"):
            tid = db.x("INSERT INTO topics (site_id, name, position, created_at) VALUES (?,?,?,?)",
                       (site_id, BRAND_TOPIC, 99, db.now()))
            for qu in res["brand_questions"]:
                _insert_question(site_id, tid, qu["text"], qu.get("lang") or "de", 1)
        db.x("UPDATE sites SET state='draft', state_msg='' WHERE id=?", (site_id,))
        if site["auto_start"]:
            from . import measure
            measure.enqueue(site_id, "auto")
    except Exception as e:
        db.x("UPDATE sites SET state='error', state_msg=? WHERE id=?", (str(e)[:300], site_id))


def _insert_question(site_id, topic_id, text, lang, is_brand):
    n = db.one("SELECT COUNT(*) AS n FROM questions WHERE site_id=?", (site_id,))["n"]
    return db.x("INSERT INTO questions (site_id, topic_id, code, text, lang, is_brand, series_start, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (site_id, topic_id, f"F{n + 1}", text.strip(), lang, is_brand, db.now(), db.now()))


# ---------- Pflege durch den Nutzer ----------

def topics(site_id):
    return db.q("SELECT * FROM topics WHERE site_id=? AND merged_into IS NULL ORDER BY position, id", (site_id,))


def _topic(tid):
    return db.one("SELECT * FROM topics WHERE id=?", (tid,))


def suggest_topic(site_id, text):
    """Passendes bestehendes Themenfeld für eine neue Frage: größte Wortüberschneidung."""
    best, score = None, -1
    w = words(text)
    for t in topics(site_id):
        if t["name"] == BRAND_TOPIC:
            continue
        qs = db.q("SELECT text FROM questions WHERE topic_id=? AND active=1", (t["id"],))
        s = len(w & words(t["name"] + " " + " ".join(r["text"] for r in qs)))
        if s > score:
            best, score = t, s
    return best


def add_question(site_id, text, topic_id=None, is_brand=0):
    site = db.one("SELECT * FROM sites WHERE id=?", (site_id,))
    t = _topic(topic_id) if topic_id else suggest_topic(site_id, text)
    if not t:
        t = _topic(add_topic(site_id, "Allgemein"))
    qid = _insert_question(site_id, t["id"], text, guess_lang(text, site["language"] or "de"), is_brand)
    db.log_change(site_id, "question_added", t["id"], qid, text=text, topic=t["name"])
    return qid


def update_question(qid, text=None, topic_id=None):
    qu = db.one("SELECT * FROM questions WHERE id=?", (qid,))
    if text is not None and text.strip() and text.strip() != qu["text"]:
        # Neuer Wortlaut = neue Messreihe: der Verlauf dieser Frage beginnt neu.
        db.x("UPDATE questions SET text=?, lang=?, revision=revision+1, series_start=? WHERE id=?",
             (text.strip(), guess_lang(text, qu["lang"]), db.now(), qid))
        db.log_change(qu["site_id"], "question_edited", qu["topic_id"], qid, old=qu["text"], new=text.strip())
    if topic_id and int(topic_id) != qu["topic_id"]:
        old, new = _topic(qu["topic_id"]), _topic(int(topic_id))
        db.x("UPDATE questions SET topic_id=? WHERE id=?", (new["id"], qid))
        db.log_change(qu["site_id"], "question_moved", new["id"], qid, text=qu["text"],
                      old_topic=old["name"], old_topic_id=old["id"], new_topic=new["name"])


def remove_question(qid):
    qu = db.one("SELECT * FROM questions WHERE id=?", (qid,))
    db.x("UPDATE questions SET active=0 WHERE id=?", (qid,))
    db.log_change(qu["site_id"], "question_removed", qu["topic_id"], qid, text=qu["text"])


def add_topic(site_id, name):
    pos = len(topics(site_id))
    tid = db.x("INSERT INTO topics (site_id, name, position, created_at) VALUES (?,?,?,?)",
               (site_id, name.strip()[:60], pos, db.now()))
    db.log_change(site_id, "topic_added", tid, name=name.strip())
    return tid


def rename_topic(tid, name):
    t = _topic(tid)
    if name.strip() and name.strip() != t["name"]:
        db.x("UPDATE topics SET name=? WHERE id=?", (name.strip()[:60], tid))
        db.log_change(t["site_id"], "topic_renamed", tid, old=t["name"], new=name.strip())


def merge_topics(src_id, dst_id):
    src, dst = _topic(src_id), _topic(dst_id)
    if not src or not dst or src["id"] == dst["id"] or src["site_id"] != dst["site_id"]:
        return
    db.x("UPDATE questions SET topic_id=? WHERE topic_id=?", (dst["id"], src["id"]))
    db.x("UPDATE topics SET merged_into=? WHERE id=?", (dst["id"], src["id"]))
    db.x("UPDATE topics SET merged_into=? WHERE merged_into=?", (dst["id"], src["id"]))
    db.log_change(src["site_id"], "topic_merged", dst["id"], old=src["name"], old_topic_id=src["id"], new=dst["name"])


def create_site(url, name="", interval="monthly", auto_start=False, tenant_id=1):
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    domain = domain_of(url)
    if not domain or "." not in domain and not domain.startswith("localhost"):
        raise ValueError("Bitte eine gültige Adresse angeben")
    return db.x("INSERT INTO sites (tenant_id, name, url, domain, interval, auto_start, created_at) VALUES (?,?,?,?,?,?,?)",
                (tenant_id, name.strip(), url, domain, interval, 1 if auto_start else 0, db.now()))
