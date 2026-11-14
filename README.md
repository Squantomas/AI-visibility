# AI-Visibility

**Wird Ihr Unternehmen gefunden, wenn künftige Kunden eine KI fragen?**

AI-Visibility ist ein webbasiertes Werkzeug für den eigenen Gebrauch. Es prüft regelmäßig, ob und wo eine
Website in fünf KI-Modellen (ChatGPT, Gemini, Perplexity, Claude, Microsoft Copilot) und in der
Websuche auftaucht, und erstellt daraus einen Bericht mit konkreten Empfehlungen und Verläufen.

Version 0.1.0 · Python · eine SQLite-Datei als Datenbank · kein Build-Schritt · Lizenz GPL-3.0

Ein Beispielbericht mit simulierten Daten liegt unter [`docs/Beispielbericht-Demo.pdf`](docs/Beispielbericht-Demo.pdf).

---

## Was das Werkzeug macht

1. **Website einlesen:** Sie geben eine Adresse ein. AI-Visibility liest die wichtigsten Seiten und schlägt
   etwa 20 Fragen vor, wie sie künftige Kunden einer KI stellen würden („Wer liefert …?“), gruppiert in
   Themenfelder. Dazu kommen zwei Fragen nach der Marke selbst.
2. **Fragen prüfen:** Vor der ersten Messung ändern, ergänzen oder streichen Sie die Fragen. Themenfelder
   lassen sich umbenennen und zusammenlegen.
3. **Messen:** Jede Frage geht an alle fünf KI-Modelle und an die Websuche. AI-Visibility zählt, in welchen
   Antworten die Website genannt wird, welche Wettbewerber stattdessen auftauchen und auf welche Quellen
   sich die Modelle stützen. Zusätzlich prüft es die Technik der Website (Titel, Beschreibungen,
   strukturierte Daten, Sperren für KI-Crawler, llms.txt und mehr).
4. **Bericht:** Trefferquote je KI-Modell, jede Frage je Kanal, Anbieteranteile je Themenfeld,
   technische Befunde und mindestens fünf priorisierte Empfehlungen. Als Webseite oder PDF.
5. **Wiederholen:** Je Website stellen Sie einen Rhythmus ein (z. B. monatlich). Es werden dieselben
   Fragen gestellt; der neue Bericht zeigt die Veränderung zur Vorprüfung und Verläufe über alle Prüfungen.

---

## Schnellstart: in fünf Minuten ausprobieren, ohne API-Schlüssel

Voraussetzung: Linux oder macOS mit **Python 3.10 oder neuer** und `git`.
Unter Ubuntu bei Bedarf vorher: `sudo apt install python3 python3-venv git`.

**1. Projekt holen und einrichten**

```bash
git clone https://github.com/Squantomas/AI-visibility.git
```

```bash
cd AI-visibility
```

```bash
python3 -m venv .venv && . .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

**2. Demo-Modus einschalten.** Im Demo-Modus sind alle Antworten simuliert; Sie brauchen weder Schlüssel
noch Internet. Berichte tragen dann deutlich den Hinweis „Demodaten“.

```bash
cp .env.example .env && sed -i 's/^DEMO_MODE=0/DEMO_MODE=1/' .env
```

(Unter macOS: `sed -i '' 's/^DEMO_MODE=0/DEMO_MODE=1/' .env`, oder die Datei `.env` im Editor öffnen und
`DEMO_MODE=1` setzen.)

**3. Eine Test-Website starten** (zweites Terminal, im selben Ordner, mit aktivierter Umgebung):

```bash
python tests/fixture_site.py
```

Sie läuft unter `http://localhost:8765` und stellt eine erfundene Firma mit typischen Schwächen dar.

**4. AI-Visibility starten** (erstes Terminal):

```bash
python run.py
```

**5. Im Browser `http://127.0.0.1:8000` öffnen**, als neue Website `http://localhost:8765` eintragen,
„Website einlesen“ klicken, die Fragen ansehen und „Erste Messung starten“. Nach wenigen Sekunden steht
der Bericht da. Ändern Sie danach eine Frage und messen Sie erneut, um die Veränderungsansicht zu sehen.

---

## Echter Betrieb: Schlüssel eintragen

Öffnen Sie die Datei `.env`, setzen Sie `DEMO_MODE=0` und tragen Sie die Schlüssel ein, die Sie haben.
Jeder fehlende Kanal erscheint im Bericht als „nicht gemessen“; die übrigen laufen trotzdem.

| Kanal | Eintrag in `.env` | Woher |
|---|---|---|
| ChatGPT | `OPENAI_API_KEY` | platform.openai.com |
| Gemini | `GEMINI_API_KEY` | aistudio.google.com |
| Perplexity | `PERPLEXITY_API_KEY` | perplexity.ai, Einstellungen → API |
| Claude | `ANTHROPIC_API_KEY` | console.anthropic.com |
| Websuche | `SEARCH_PROVIDER=brave` und `BRAVE_API_KEY` | brave.com/search/api (empfohlen); ohne Schlüssel `SEARCH_PROVIDER=duckduckgo` |
| Copilot | `COPILOT_MODE=browser` | kein Schlüssel, siehe Hinweis unten |

Danach AI-Visibility neu starten und unter **„Kanäle & Einstellungen“** je Kanal die **Testabfrage** ausführen.
So sehen Sie sofort, ob Schlüssel und Modellname passen. Die Modellnamen (`OPENAI_MODEL`, `GEMINI_MODEL`
usw.) stehen ebenfalls in `.env` und müssen zu Ihrem Konto passen.

Mindestens ein KI-Schlüssel ist auch für die **Auswertung** nötig: Fragen aus dem Website-Inhalt ableiten,
Anbieter in den Antworten erkennen und Textvorschläge zu den Empfehlungen schreiben. Ohne ihn bildet
AI-Visibility die Fragen nur aus einfachen Vorlagen.

**Copilot:** Microsoft bietet keine öffentliche Schnittstelle. Mit `COPILOT_MODE=browser` steuert AI-Visibility
die Weboberfläche von copilot.microsoft.com fern. Das ist experimentell, kann bei Änderungen der Seite
ausfallen und sollte nur nach Prüfung der Nutzungsbedingungen von Microsoft genutzt werden. Es braucht
zusätzlich Playwright (nächster Abschnitt).

**Kosten:** Eine Prüfung mit 20 Fragen sind 100 KI-Abfragen mit Websuche plus 20 Suchabfragen und einige
Auswertungsaufrufe. Die Kosten hängen von Ihren Tarifen ab; prüfen Sie sie nach der ersten echten Messung
in den Konsolen der Anbieter.

### Optional: PDF-Export und Copilot

```bash
pip install playwright && playwright install chromium
```

Ohne Playwright funktioniert alles andere; den Bericht können Sie dann im Browser über „Drucken“ als PDF
speichern.

---

## Dauerbetrieb

- **Zeitplan:** Fällige Prüfungen startet AI-Visibility selbst, solange das Programm läuft. Für einen Server oder
  Heimserver empfiehlt sich ein systemd-Dienst, der `python run.py` im Projektordner startet.
- **Zugriff von anderen Rechnern:** In `.env` `HOST=0.0.0.0` und ein `APP_PASSWORD` setzen. Die Oberfläche
  fragt dann nach dem Passwort (Benutzername beliebig). Für den Zugang aus dem Internet einen Reverse-Proxy
  mit HTTPS davorschalten.
- **Daten:** Alles liegt in `data/ai-visibility.db`. Zum Sichern genügt es, diese Datei zu kopieren, während das
  Programm beendet ist.
- **Unterbrechungen:** Nach einem Neustart setzt AI-Visibility angefangene Läufe fort. Fehlgeschlagene Abfragen
  werden dreimal wiederholt und lassen sich auf der Seite des Laufs erneut anstoßen.

---

## Regeln, die die Messreihe vergleichbar halten

- Bei jeder Wiederholung werden **dieselben Fragen** gestellt, bis Sie sie ausdrücklich ändern.
- Ändern Sie den **Wortlaut** einer Frage, beginnt ihr Verlauf neu; der Bericht markiert sie mit „Neubeginn“.
- **Veränderungswerte** rechnen nur mit Fragen, die in beiden Prüfungen im selben Wortlaut gestellt wurden.
- **Themenfelder** bleiben bestehen, auch wenn Fragen hinzukommen. Umbenennen, Zusammenlegen und
  Verschieben werden protokolliert und im nächsten Bericht am Feld als „geändert“ ausgewiesen.
- Die **Anbieterliste** bereinigen Sie je Website (zusammenlegen, ausblenden, „ist unsere Marke“). Das gilt
  für alle Berichte dieser Website, auch rückwirkend.
- Welche **Schreibweisen der Marke** als Treffer zählen, stellen Sie je Website ein. Umlaute werden in allen
  Varianten erkannt (ö, oe, o).

---

## Für Entwickler

Tests (laufen im Demo-Modus gegen die lokale Test-Website, ohne Netz):

```bash
pip install pytest && python -m pytest -q tests
```

| Datei | Aufgabe |
|---|---|
| `run.py` | Startet die Weboberfläche |
| `app/main.py`, `app/templates/` | Weboberfläche und Berichtsvorlage (FastAPI, Jinja2) |
| `app/crawl.py` | Seiten finden und lesen, technische Prüfpunkte |
| `app/questions.py` | Fragen und Themenfelder ableiten und pflegen, Änderungsprotokoll |
| `app/channels.py`, `app/llm.py` | Die sechs Messkanäle, Auswertungsmodell, Demo-Antworten |
| `app/measure.py` | Messlauf, Anbietererkennung, Zeitplanung und Warteschlange |
| `app/recommend.py` | Regeln für Empfehlungen, optionale Textvorschläge |
| `app/report.py` | Kennzahlen, Anbieteranteile, Veränderungen, Verläufe |
| `tests/` | Tests und die erfundene Test-Website |

Alle Einstellungen stehen kommentiert in `.env.example`.

---

## Stand und Grenzen von Version 0.1.0

- Geprüft ist der vollständige Ablauf im Demo-Modus. Die Anbindungen an die echten KI-Dienste sind
  geschrieben, aber noch nicht gegen die Live-Schnittstellen getestet. Bitte vor dem ersten Einsatz die
  Testabfragen unter „Kanäle & Einstellungen“ ausführen und Abweichungen melden.
- Die Schnittstellen der KI-Modelle antworten nicht immer genau wie deren Apps. Die Websuche ist eine
  unabhängige Suche als Annäherung, nicht Google.
- Je Frage und Kanal gibt es eine Abfrage pro Prüfung. Einzelne Treffer schwanken; belastbar ist das
  Muster über mehrere Fragen und Prüfungen.
- Für ein späteres Angebot an Kunden ist die Datentrennung je Mandant (`tenant_id`) vorbereitet.
  Anmeldung je Konto und Rechteverwaltung fehlen noch; bis dahin gibt es ein gemeinsames Passwort.

Änderungen je Version: [CHANGELOG.md](CHANGELOG.md) · Stand und Kontext für die Weiterentwicklung: [CLAUDE.md](CLAUDE.md)
