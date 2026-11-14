# Kontext für Claude-Sitzungen: Peilung (AI-visibility)

Diese Datei übergibt den Stand an die nächste Sitzung. Bitte zuerst ganz lesen, dann README.md und
CHANGELOG.md. Bei Änderungen am Stand diesen Abschnitt „Stand und nächste Schritte“ aktualisieren.

## Worum es geht

Webbasiertes Werkzeug für den eigenen Gebrauch (später evtl. Angebot für Kunden). Für eine beliebige
Website leitet es Fragen aus deren Inhalt ab, prüft regelmäßig, wie die Website in fünf KI-Modellen
(ChatGPT, Gemini, Perplexity, Claude, Copilot) und der Websuche gefunden wird, zeigt technische Schwächen
und erstellt Berichte mit konkreten Empfehlungen und Verläufen.

**Nutzer:** Marketing- und Geschäftsverantwortliche kleiner und mittlerer Unternehmen sowie Agenturen.
**Auftraggeber:** CTO, hat lange nicht programmiert, arbeitet gern mit Python unter Ubuntu. Erklärungen
deshalb ohne Fachjargon, Befehle einzeln und kopierfertig. Kommunikation und Oberfläche auf **Deutsch**.

Vorbild für die Methode war ein fremder PDF-Bericht („Sichtprobe“ einer Agentur). **Non-Goal:** keine
Inhalte, Texte, Namen oder Gestaltung daraus übernehmen, nur die Methode nachbauen.

## Erfolgskriterien (Vorgabe des Auftraggebers)

1. Bericht für eine neue Website in unter 30 Minuten ohne manuelle Arbeit.
2. Bericht enthält Trefferquote je KI-Modell, Wettbewerbsanteile und mindestens 5 priorisierte Empfehlungen.
3. Wiederholungsrhythmus je Website (z. B. monatlich); neuer Bericht zeigt Veränderung zur Vorprüfung.
4. 20 Websites pro Monat ohne manuelle Nacharbeit.
5. Etwa 20 Fragen je neuer Website aus dem Inhalt; Nutzer kann sie vor der Messung ändern/ergänzen/streichen.
6. Bei jeder Wiederholung dieselben Fragen; ändert der Nutzer eine Frage, beginnt deren Verlauf neu, und
   der Neubeginn ist im Bericht gekennzeichnet.
7. Jede Frage bei jeder Prüfung an alle fünf KI-Modelle und die Websuche; Bericht zeigt je Frage und Kanal,
   ob und wo die Website erscheint (Websuche: ob unter den ersten zehn).
8. Bericht zeigt je Prüfung, welche Anbieter genannt werden und mit welchem Anteil, getrennt nach
   Themenfeld; Anbieter automatisch erkannt, Liste je Website bereinigbar.
9. Fragen automatisch in Themenfelder gruppiert; Felder umbenennen, zusammenlegen, Fragen verschieben;
   Anbieteranteile beziehen sich auf diese Felder.
10. Themenfelder bleiben bei Wiederholungen bestehen, auch wenn Fragen dazukommen; Änderungen an Feldern
    im Bericht gekennzeichnet.

Constraint: zunächst intern, aber so gebaut, dass ein Kundenangebot möglich bleibt.

## Architektur

Python 3.10+, FastAPI + Jinja2, SQLite (`data/peilung.db`), kein JS-Build. Hintergrund-Worker als Thread
im selben Prozess (Warteschlange in der Tabelle `runs`, Läufe nacheinander, wiederaufnehmbar).

| Datei | Aufgabe |
|---|---|
| `app/config.py` | `.env` laden, Kanalliste `CHANNELS`, `channel_status()`, Wahl des Auswertungsmodells |
| `app/db.py` | Schema, Helfer `q/one/x`, `log_change()` für das Änderungsprotokoll |
| `app/crawl.py` | robots.txt, Sitemap, llms.txt, Seiten lesen; `audit()` = 12 technische Prüfpunkte |
| `app/questions.py` | Fragenvorschlag (KI-Prompt oder Heuristik ohne KI), Pflege von Fragen und Feldern |
| `app/llm.py` | Anbindungen OpenAI (Responses API + web_search), Gemini (google_search), Perplexity (sonar), Claude (Anthropic-SDK, `web_search_20260209`, serverseitige `fallbacks`), `analyse()` für JSON-Auswertung, `retry()` |
| `app/channels.py` | Die sechs Messkanäle inkl. Copilot per Playwright und Websuche (Brave oder DuckDuckGo); deterministische Demo-Antworten |
| `app/measure.py` | Messlauf (`execute`), Treffererkennung, Anbietererkennung, Zeitplanung `scheduler_tick`, `start_worker` |
| `app/recommend.py` | Regelbasierte Empfehlungen (immer ≥ 5), optional KI-Textvorschläge und Kernaussagen |
| `app/report.py` | Berichtsdaten **zur Laufzeit** aus gespeicherten Antworten berechnen |
| `app/main.py` | Routen, Basic-Auth über `APP_PASSWORD`, PDF via Playwright, SVG-Verlaufsgrafik `linechart()` |
| `app/templates/report.html`, `app/static/report.css` | Bericht (Web und Druck/PDF) |
| `tests/test_core.py` | Tests inkl. vollständigem Zyklus im Demo-Modus |
| `tests/fixture_site.py` | Erfundene Firmen-Website „Brückner Filtertechnik“ mit typischen Schwächen, Port 8765 |

## Wichtige Entwurfsentscheidungen (nicht versehentlich aufbrechen)

- **Vergleichbarkeit:** Beim Start eines Laufs werden die aktiven Fragen in `run_questions` eingefroren
  (mit `revision`). Ändert der Nutzer den Wortlaut, steigt `questions.revision` → Bericht markiert
  „Neubeginn“. Veränderungswerte rechnen nur über Fragen mit gleicher `question_id` **und** `revision`.
- **Änderungsprotokoll:** Jede Pflegeaktion schreibt in `changes`. Jeder Lauf speichert `change_mark`
  (höchste `changes.id` beim Start). Der Bericht zeigt Änderungen zwischen `change_mark` des Vorlaufs und
  des aktuellen Laufs. Bewusst über IDs statt Zeitstempel (Zeitstempel kollidierten bei schnellen Läufen).
- **Zusammenlegen statt Löschen:** Themenfelder (`topics.merged_into`) und Anbieter (`vendors.merged_into`,
  `hidden`) werden nur verknüpft. `report.topic_map()`/`vendor_map()` lösen die Ketten auf, daher wirkt
  jede Bereinigung rückwirkend auf alle Berichte.
- **Treffer:** `textutil.mentions()` prüft alle Markenschreibweisen in zwei Umlaut-Faltungen (ö→oe, ö→o)
  plus Domain. Ändern der Schreibweisen ruft `measure.recompute_mentions()` für alle Läufe auf.
- **Fehlende Kanäle** werden als `skipped` gespeichert und im Bericht als „nicht gemessen“ ausgewiesen,
  nie stillschweigend weggelassen. Ein Lauf ohne jede erfolgreiche Antwort schlägt mit klarer Meldung fehl.
- **Demo-Modus** (`DEMO_MODE=1`): alle Antworten simuliert, aber deterministisch (Hash von Site, Frage,
  Revision, Kanal). Berichte tragen ein Banner „Demodaten“. Runs haben `mode` demo/live; Verläufe mischen
  die Modi nicht.
- **Mandantenfähigkeit vorbereitet:** `sites.tenant_id`, in `main.py` fest `TENANT = 1`.
- **Modellwahl Claude:** Standard `claude-opus-5-5` (in `.env` änderbar), mit `fallbacks="default"`
  (Beta `server-side-fallback-2026-07-01`). Voraussetzung `anthropic>=2.8`.
- Bericht nutzt bewusst eine **eigene** Gestaltung (Blau für die eigene Marke, Grün gefüllt = genannt).

## Entwickeln und prüfen

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest
```

```bash
python -m pytest -q tests
```

Manuell: `.env` aus `.env.example` mit `DEMO_MODE=1`, dann `python tests/fixture_site.py` und
`python run.py`, im Browser `http://127.0.0.1:8000`, Website `http://localhost:8765` anlegen.

Vor jedem Commit: Tests grün, Oberfläche/Bericht nach Änderungen im Browser ansehen (Playwright ist in
Cloud-Sitzungen vorinstalliert; für PDF `CHROMIUM_PATH=/opt/pw-browsers/chromium` setzen). Bei
Hintergrundservern lokale Adressen vom Proxy ausnehmen (`NO_PROXY=...,localhost`).

## Stand und nächste Schritte (Version 0.1.0, Stand 2026-11-14)

**Fertig und getestet (nur Demo-Modus):** gesamter Ablauf von Einlesen bis Bericht, Wiederholungen,
Kennzeichnung von Änderungen, Anbieterbereinigung, PDF-Export, Zeitplanung. 4 Tests grün.

**Nicht getestet:** alle Live-Kanäle. Die Cloud-Sitzung hatte weder API-Schlüssel noch Zugriff auf die
APIs der Anbieter; DuckDuckGo wurde vom Proxy blockiert (403).

**Offene Punkte, nach Priorität:**
1. Live-Test mit echten Schlüsseln: je Kanal Testabfrage unter „Kanäle & Einstellungen“, dann eine echte
   Website messen. Antwortformate von OpenAI/Gemini/Perplexity gegen die aktuellen API-Dokumentationen
   prüfen (Zitatfelder, Modellnamen in `.env.example`: `gpt-5`, `gemini-2.5-flash`, `sonar` sind Annahmen).
2. Qualität der KI-Fragenableitung an echten Websites prüfen (Prompt in `questions.py`, Ziel ~20 Fragen).
   Die Heuristik ohne KI liefert deutlich weniger Fragen.
3. Laufzeit und Kosten je Prüfung mit echten Kanälen messen (Kriterium 1 und 4). Copilot ist seriell und
   am langsamsten.
4. Copilot-Kanal (Playwright gegen copilot.microsoft.com) ist experimentell und ungetestet; Selektoren in
   `.env` überschreibbar. Nutzungsbedingungen von Microsoft klären.
5. Websuche für Dauerbetrieb auf Brave Search umstellen (DuckDuckGo drosselt).
6. systemd-Unit für Dauerbetrieb beilegen.
7. Später für Kunden: Anmeldung je Konto, Zuordnung zu `tenant_id`, eigenes Erscheinungsbild der Berichte.

**Release-Hinweis:** Der Git-Tag `v0.1.0` und das GitHub-Release konnten aus der Cloud-Sitzung nicht
veröffentlicht werden (Tag-Push und Release-API dort gesperrt). Falls auf GitHub noch kein Tag `v0.1.0`
existiert, muss der Nutzer ihn lokal setzen: `git tag -a v0.1.0 a9b2279 -m "Peilung 0.1.0"` und
`git push origin v0.1.0`, dann das Release auf GitHub anlegen. Neue Versionen in `app/__init__.py`
(`__version__`) und `CHANGELOG.md` pflegen.

## Konventionen

- Oberflächen- und Berichtstexte auf Deutsch, sachlich, ohne Werbesprache, deutsche Anführungszeichen „…“.
- Keine persönlichen Daten des Auftraggebers in Code, Commits oder Anfragen an externe Dienste.
- Keine API-Schlüssel ins Repository; `.env` und `data/` sind in `.gitignore`.
- Bericht: Farbe nie allein als Bedeutungsträger (Symbole + Legende), keine Doppelachsen.
