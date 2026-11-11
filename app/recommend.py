"""Empfehlungen: Regeln leiten aus Messung und Technikprüfung priorisierte Maßnahmen ab.

Die Regeln liefern immer mindestens fünf Empfehlungen. Ist ein Auswertungsmodell vorhanden,
ergänzt es Textvorschläge und die Kernaussagen; ohne Modell bleibt der Bericht trotzdem vollständig.
"""
import json

from . import config, db, llm, report

LEVEL = {3: "hoch", 2: "mittel", 1: "niedrig"}


def candidates(rep):
    out = []

    def add(key, impact, effort_h, title, place, evidence, action):
        effort = f"{int(effort_h * 60)} Min" if effort_h < 1 else (f"{effort_h:g} Std" if effort_h < 8 else f"{effort_h / 8:g} Tag(e)")
        out.append({"key": key, "impact": impact, "hours": effort_h, "title": title, "place": place,
                    "evidence": evidence, "action": action, "effort": effort})

    checks = {c["key"]: c for c in rep["checks"]}
    m = lambda k: checks.get(k, {}).get("metrics", {})
    st = lambda k: checks.get(k, {}).get("status")
    name = rep["site"]["name"]

    if st("aibots") == "fehlt":
        add("aibots", 3, .25, "KI-Crawler nicht aussperren", "robots.txt",
            checks["aibots"]["finding"],
            "Die Sperren für die genannten Crawler aus der robots.txt entfernen. Solange sie gelten, können die "
            "betroffenen KI-Modelle die Website nicht lesen und nennen stattdessen andere Quellen.")
    if st("reach") == "fehlt":
        add("reach", 3, 1, "Website erreichbar machen", "Server", checks["reach"]["finding"],
            "Die Startseite war für die Prüfung nicht abrufbar. Erreichbarkeit, Weiterleitungen und Bot-Schutz prüfen.")
    if m("title").get("weak_home") or st("title") in ("teilweise", "fehlt"):
        add("title", 3, .5, "Seitentitel mit dem Angebot füllen", "Startseite und wichtigste Seiten",
            checks["title"]["finding"],
            "Der Titel der Startseite soll in einem Satz sagen, was das Unternehmen anbietet und für wen. "
            "Jede wichtige Seite bekommt einen eigenen Titel mit ihrem Fachbegriff.")
    if st("description") in ("teilweise", "fehlt"):
        add("description", 2, 3, "Beschreibungen für die wichtigsten Seiten schreiben", "Seitenkopf (meta description)",
            checks["description"]["finding"],
            "Für die rund 20 wichtigsten Seiten je eine Beschreibung mit 140 bis 160 Zeichen: Angebot, Zielgruppe, "
            "ein Beleg. Suchmaschinen zeigen sie im Treffer, KI-Modelle nutzen sie als Kurzfassung.")
    if st("h1") in ("teilweise", "fehlt"):
        add("h1", 2, 1, "Eine eindeutige Hauptüberschrift je Seite", "Seitenvorlagen",
            checks["h1"]["finding"],
            "Jede Seite erhält genau eine H1 mit dem Thema der Seite; weitere Überschriften werden H2 oder H3.")
    if st("structured") in ("teilweise", "fehlt"):
        add("structured", 2, 3, "Unternehmen mit strukturierten Daten auszeichnen", "Seitenvorlage (JSON-LD)",
            checks["structured"]["finding"],
            "Organisation mit Name, Anschrift, Gründungsjahr, Tätigkeitsfeldern und Profilen auszeichnen; "
            "Produkte und Leistungen folgen. So ordnen Suchmaschinen und KI-Modelle das Unternehmen sicher zu.")
    if st("llms") == "fehlt":
        add("llms", 1, 1, "llms.txt mit Kurzprofil anlegen", "Hauptverzeichnis der Website",
            "Es gibt keine llms.txt.",
            "Eine kurze Textdatei mit Firmenprofil und Links zu den wichtigsten Bereichen ablegen. Der Nutzen ist "
            "noch nicht bei allen Modellen belegt, der Aufwand aber gering.")
    if st("alt") in ("teilweise", "fehlt"):
        add("alt", 1, 6, "Bilder beschreiben", "Bilder der Produkt- und Leistungsseiten",
            checks["alt"]["finding"],
            "Alternativtexte ergänzen, zuerst für Produktbilder: Produktname und Funktion in einem kurzen Satz.")
    if st("text") in ("teilweise", "fehlt"):
        add("text", 2, 8, "Dünne Seiten mit Inhalt füllen", "Seiten mit wenig Text",
            checks["text"]["finding"],
            "Seiten unter 200 Wörtern ausbauen oder zusammenlegen: Was ist es, für wen, welcher Nutzen, welcher Beleg.")
    if st("sitemap") in ("teilweise", "fehlt"):
        add("sitemap", 2, 1, "Sitemap und robots.txt bereitstellen", "Hauptverzeichnis der Website",
            checks["sitemap"]["finding"],
            "Eine aktuelle XML-Sitemap erzeugen und in der robots.txt nennen, damit alle Seiten gefunden werden.")
    if st("index") in ("teilweise", "fehlt"):
        add("index", 2, .5, "noindex-Seiten prüfen", "Seiten mit noindex", checks["index"]["finding"],
            "Prüfen, ob die ausgeschlossenen Seiten wirklich nicht gefunden werden sollen.")

    # --- Inhalte: schwache Themenfelder und Fragen ohne Nennung
    fach = [t for t in rep["topics"] if not t["is_brand"] and t["total"]]
    avg = report.pct(*rep["head"]["nb"]) or 0
    lead = {t["id"]: None for t in rep["vendors"]["topics"]}
    for i, t in enumerate(rep["vendors"]["topics"]):
        best = max((r for r in rep["vendors"]["rows"] if not r["self"]), key=lambda r: r["cells"][i]["share"] or 0, default=None)
        if best and best["cells"][i]["share"]:
            lead[t["id"]] = (best["name"], best["cells"][i]["share"])
    for t in sorted(fach, key=lambda t: t["rate"])[:3]:
        if t["rate"] <= max(35, avg - 5):
            zero = [qu for qu in rep["questions"] if qu["tid"] == t["id"] and qu["ai_hits"] == 0]
            ld = lead.get(t["id"])
            ev = f"{t['hits']} von {t['total']} Antworten im Feld „{t['name']}“ nennen {name}"
            ev += f"; am häufigsten genannt: {ld[0]} ({ld[1]} %)." if ld else "."
            if zero:
                ev += " Ohne jede Nennung: " + ", ".join(qu["code"] for qu in zero[:6]) + "."
            add(f"topic:{t['id']}", 3, 3, f"Themenfeld „{t['name']}“ sichtbar machen", f"Seite(n) zu „{t['name']}“", ev,
                "Eine eigene Seite, die das Themenfeld beim Namen nennt und die gemessenen Fragen in ganzen Sätzen "
                "beantwortet: Leistung, Einsatzbereich, Belege. Die Fachbegriffe aus den Fragen gehören in Titel, "
                "Hauptüberschrift und ersten Absatz.")
    zero_all = [qu for qu in rep["questions"] if not qu["is_brand"] and qu["ai_total"] and qu["ai_hits"] == 0]
    if zero_all:
        add("faq", 2, 2, "Fragen ohne Nennung direkt beantworten", "Fragen-und-Antworten-Abschnitte der Fachseiten",
            f"{len(zero_all)} von {len([q for q in rep['questions'] if not q['is_brand']])} Fachfragen nennt kein KI-Modell mit "
            f"{name}: " + ", ".join(qu["code"] for qu in zero_all[:8]) + ".",
            "Zu jeder dieser Fragen einen kurzen Abschnitt mit der Frage als Überschrift und einer Antwort in zwei bis "
            "drei Sätzen auf die passende Seite stellen. KI-Modelle übernehmen bevorzugt Absätze, die eine Frage vollständig beantworten.")

    # --- Quellen und einzelne Kanäle
    third = [s for s in rep["sources"] if not s["own"] and s["count"] >= 2 and s["with_us"] < s["count"]]
    if third:
        add("sources", 2, 4, "Dort stehen, wo die KI-Modelle nachlesen", "Verzeichnisse, Fachportale, Partnerseiten",
            "Häufig zitiert, oft ohne " + name + ": " + ", ".join(f"{s['domain']} ({s['with_us']}/{s['count']})" for s in third[:5]) + ".",
            "Prüfen, welche dieser Seiten einen Eintrag, ein Profil oder einen Fachbeitrag zulassen, und dort mit "
            "einheitlichen Angaben (Name, Sitz, Leistungen, Link) vertreten sein. Seiten von Wettbewerbern zeigen, "
            "welche Detailtiefe die Modelle zitieren.")
    ai = [mo for mo in rep["ai_models"] if mo["measured"] and mo["total_nb"]]
    if ai:
        weak = min(ai, key=lambda mo: mo["hits_nb"] / mo["total_nb"])
        if weak["hits_nb"] / weak["total_nb"] < .3:
            hint = {"gemini": "Gemini stützt sich auf den Google-Index: Indexierung prüfen und Unternehmensprofil bei Google pflegen.",
                    "copilot": "Copilot stützt sich auf Bing: Website in den Bing Webmaster Tools anmelden und Sitemap einreichen.",
                    "chatgpt": "ChatGPT sucht über eigene Crawler und Bing: Zugang für OAI-SearchBot erlauben, Bing-Indexierung prüfen.",
                    "perplexity": "Perplexity zitiert gern Verzeichnisse und Fachportale: dort mit aktuellem Profil vertreten sein.",
                    "claude": "Claude zitiert häufig Seiten Dritter: Händler, Partner und Verzeichnisse mit korrekten Angaben versorgen."}[weak["key"]]
            add("model:" + weak["key"], 2, 2, f"Schwächstes Modell gezielt angehen: {weak['label']}", "Suchindex und externe Quellen",
                f"{weak['label']} nennt {name} in {weak['hits_nb']} von {weak['total_nb']} Fachantworten.", hint)
    wh, wt = rep["head"]["web"]
    if wt and wh / wt < .3:
        add("web", 2, 4, "Grundlagen für die klassische Suche stärken", "Titel, Überschriften, interne Verlinkung",
            f"Bei {wh} von {wt} Fragen steht {rep['site']['domain']} unter den ersten zehn Treffern der Websuche.",
            "Je Themenfeld eine Seite auf den Suchbegriff der Fragen ausrichten und von Startseite und Navigation "
            "verlinken. KI-Modelle mit Websuche lesen dieselben Treffer.")

    # --- Immer sinnvoll; füllt auf mindestens fünf auf
    evergreen = [
        ("facts", 1, 1, "Fakten überall gleich schreiben", "Website, Profile, Verzeichnisse",
         "KI-Modelle vergleichen Quellen und geben Abweichungen weiter.",
         "Name, Sitz, Gründungsjahr, Standorte und Leistungsbereiche einmal festlegen und auf Website, "
         "Unternehmensprofilen und in Verzeichnissen wortgleich verwenden."),
        ("queries", 1, 1, "Fragenkatalog mit echten Anfragen abgleichen", "Fragenliste in diesem Werkzeug",
         "Die Fragen sind aus dem Website-Inhalt abgeleitet.",
         "Mit dem Vertrieb prüfen, welche Fragen Kunden tatsächlich stellen. Ergänzungen erhalten einen eigenen "
         "Verlauf; bestehende Fragen möglichst unverändert lassen, damit die Messreihe vergleichbar bleibt."),
        ("log", 1, .5, "Umgesetzte Maßnahmen mit Datum festhalten", "Internes Protokoll",
         "Der Verlauf zeigt Veränderungen, aber nicht ihre Ursache.",
         "Zu jeder umgesetzten Maßnahme das Datum notieren. So lässt sich bei der nächsten Prüfung ablesen, "
         "welche Maßnahme wie stark gewirkt hat."),
    ]
    out.sort(key=lambda r: (-r["impact"], r["hours"]))
    for ev in evergreen:
        if len(out) >= 8:
            break
        if len(out) < 5 or ev[0] == "facts":
            add(*ev)
    return out[:10]


def fallback_findings(rep):
    h, f = rep["head"], []
    name = rep["site"]["name"]
    if h["ai"][1]:
        f.append(f"{h['ai'][0]} von {h['ai'][1]} Antworten der KI-Modelle nennen {name}"
                 + (f"; ohne die Markenfragen {h['nb'][0]} von {h['nb'][1]}." if h["brand"][1] else "."))
    fach = sorted([t for t in rep["topics"] if not t["is_brand"] and t["total"]], key=lambda t: -t["rate"])
    if len(fach) > 1:
        f.append(f"Am stärksten ist das Themenfeld „{fach[0]['name']}“ ({fach[0]['rate']} %), am schwächsten "
                 f"„{fach[-1]['name']}“ ({fach[-1]['rate']} %).")
    ai = sorted([m for m in rep["ai_models"] if m["measured"]], key=lambda m: -(m["rate"] or 0))
    if len(ai) > 1:
        f.append(f"Die Modelle unterscheiden sich: {ai[0]['label']} nennt {name} in {ai[0]['rate']} % der Antworten, "
                 f"{ai[-1]['label']} in {ai[-1]['rate']} %.")
    rivals = [r for r in rep["vendors"]["ranking"] if not r["self"]][:3]
    if rivals:
        f.append("Am häufigsten daneben oder stattdessen genannt: " + ", ".join(f"{r['name']} ({r['share']} %)" for r in rivals) + ".")
    if h["web"][1]:
        f.append(f"In der Websuche steht {rep['site']['domain']} bei {h['web'][0]} von {h['web'][1]} Fragen unter den ersten zehn Treffern.")
    if h["d_ai"] is not None:
        f.append(f"Veränderung zur Vorprüfung: {h['d_ai']:+d} Prozentpunkte bei den KI-Modellen "
                 f"(vergleichbare Basis: {h['comparable']} unveränderte Fragen).")
    bad = [c["label"] for c in rep["checks"] if c["status"] == "fehlt"]
    if bad:
        f.append("Technisch fehlt: " + ", ".join(bad) + ".")
    return f


ENRICH_SYSTEM = """Du berätst ein Unternehmen zur Sichtbarkeit in KI-Assistenten und Suchmaschinen. Du erhältst
Messergebnisse und eine Liste regelbasiert ermittelter Empfehlungen. Schreibe sachlich, konkret, auf Deutsch,
ohne Werbesprache. Erfinde keine Fakten über das Unternehmen: Was du nicht aus den Angaben weißt, setzt du als
Platzhalter in spitze Klammern, z. B. <Zahl der Standorte bitte ergänzen>."""


def build(run_id):
    rep = report.build(run_id)
    recs = candidates(rep)
    findings = fallback_findings(rep)
    provider = None if config.demo_mode() else config.analysis_provider()
    if provider:
        site = rep["site"]
        payload = {
            "unternehmen": site["name"], "website": site["url"],
            "profil": (db.jload(site["profile"], {}) or {}).get("summary", ""),
            "kernzahlen": findings,
            "fragen": [{"code": q["code"], "feld": q["topic"], "frage": q["text"], "nennungen": f"{q['ai_hits']}/{q['ai_total']}"}
                       for q in rep["questions"]],
            "technik": [{"punkt": c["label"], "status": c["status"], "befund": c["finding"]} for c in rep["checks"]],
            "empfehlungen": [{"key": r["key"], "titel": r["title"], "beleg": r["evidence"]} for r in recs],
        }
        try:
            res = llm.analyse(provider, ENRICH_SYSTEM, json.dumps(payload, ensure_ascii=False) + """

Aufgabe:
1. "findings": drei bis fünf Kernaussagen zum Befund, je ein bis zwei Sätze, mit den Zahlen aus der Messung.
2. "drafts": zu jeder Empfehlung (Schlüssel = key) ein fertiger Textvorschlag zum Einfügen, passend zur Maßnahme
   (z. B. Seitentitel und Beschreibung, erster Absatz, zwei bis drei Fragen mit Antworten, Inhalt der llms.txt).
   Höchstens 120 Wörter je Vorschlag. Wo kein Text sinnvoll ist, leerer String.

Antwortformat (JSON): {"findings": ["..."], "drafts": {"<key>": "..."}}""")
            findings = [x for x in res.get("findings", []) if isinstance(x, str)] or findings
            for r in recs:
                r["draft"] = (res.get("drafts", {}).get(r["key"]) or "").strip()
        except Exception:
            pass
    db.x("DELETE FROM recommendations WHERE run_id=?", (run_id,))
    with db.conn() as c:
        for i, r in enumerate(recs):
            c.execute("INSERT INTO recommendations (run_id, prio, key, title, level, effort, place, evidence, action, draft) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (run_id, i + 1, r["key"], r["title"], LEVEL[r["impact"]], r["effort"], r["place"],
                       r["evidence"], r["action"], r.get("draft", "")))
    db.x("UPDATE runs SET summary=? WHERE id=?", (json.dumps({"findings": findings}, ensure_ascii=False), run_id))
