# AI-visibility (Peilung)

**Wird Ihr Unternehmen gefunden, wenn künftige Kunden eine KI fragen?**

Peilung ist ein webbasiertes Werkzeug für den eigenen Gebrauch. Es prüft regelmäßig, ob und wo eine
Website in fünf KI-Modellen (ChatGPT, Gemini, Perplexity, Claude, Microsoft Copilot) und in der
Websuche auftaucht, und erstellt daraus einen Bericht mit konkreten Empfehlungen und Verläufen.

Version 0.1.0 · Python · eine SQLite-Datei als Datenbank · kein Build-Schritt · Lizenz GPL-3.0

Ein Beispielbericht mit simulierten Daten liegt unter [`docs/Beispielbericht-Demo.pdf`](docs/Beispielbericht-Demo.pdf).

---

## Was das Werkzeug macht

1. **Website einlesen:** Sie geben eine Adresse ein. Peilung liest die wichtigsten Seiten und schlägt
   etwa 20 Fragen vor, wie sie künftige Kunden einer KI stellen würden („Wer liefert …?“), gruppiert in
   Themenfelder. Dazu kommen zwei Fragen nach der Marke selbst.
2. **Fragen prüfen:** Vor der ersten Messung ändern, ergänzen oder streichen Sie die Fragen. Themenfelder
   lassen sich umbenennen und zusammenlegen.
3. **Messen:** Jede Frage geht an alle fünf KI-Modelle und an die Websuche. Peilung zählt, in welchen
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

**4. Peilung starten** (erstes Terminal):

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
| Claude über Ihr Claude-Abo | `CLAUDE_CODE_MODE=on` | kein Schlüssel, siehe „Claude über das Claude-Abo“ |
| Google KI-Übersicht | `GOOGLE_AI_MODE=on` | kein Schlüssel, Ihr eigener Chrome, siehe „Google KI-Übersicht“ |
| Weitere Modelle über OpenRouter | `OPENROUTER_API_KEY` und `OPENROUTER_MODELS` | openrouter.ai, siehe nächster Abschnitt |
| Websuche | `SEARCH_PROVIDER=brave` und `BRAVE_API_KEY` | brave.com/search/api (empfohlen); ohne Schlüssel `SEARCH_PROVIDER=duckduckgo`; ausschalten mit `SEARCH_PROVIDER=off` |
| Copilot | `COPILOT_MODE=browser` | kein Schlüssel, siehe Hinweis unten |

Danach Peilung neu starten und unter **„Kanäle & Einstellungen“** je Kanal die **Testabfrage** ausführen.
So sehen Sie sofort, ob Schlüssel und Modellname passen. Die Modellnamen (`OPENAI_MODEL`, `GEMINI_MODEL`
usw.) stehen ebenfalls in `.env` und müssen zu Ihrem Konto passen.

Mindestens ein KI-Schlüssel ist auch für die **Auswertung** nötig: Fragen aus dem Website-Inhalt ableiten,
Anbieter in den Antworten erkennen und Textvorschläge zu den Empfehlungen schreiben. Ohne ihn bildet
Peilung die Fragen nur aus einfachen Vorlagen.

**Copilot:** Microsoft bietet keine öffentliche Schnittstelle. Mit `COPILOT_MODE=browser` steuert Peilung
die Weboberfläche von copilot.microsoft.com fern. Das ist experimentell, kann bei Änderungen der Seite
ausfallen und sollte nur nach Prüfung der Nutzungsbedingungen von Microsoft genutzt werden. Es braucht
zusätzlich Playwright (nächster Abschnitt).

**Kosten:** Eine Prüfung mit 20 Fragen sind 100 KI-Abfragen mit Websuche plus 20 Suchabfragen und einige
Auswertungsaufrufe. Die Kosten hängen von Ihren Tarifen ab; prüfen Sie sie nach der ersten echten Messung
in den Konsolen der Anbieter.

### Weitere Modelle über OpenRouter

Über [openrouter.ai](https://openrouter.ai) erreichen Sie mit einem einzigen Schlüssel mehrere hundert
Modelle, etwa GPT, Claude, Gemini, Grok, Llama, Mistral, DeepSeek oder Perplexity Sonar. Jedes Modell, das
Sie auswählen, ist im Bericht ein **eigener Kanal**. Es wird wie die übrigen KI-Modelle mit eingeschalteter
Websuche befragt. Die Websuche ist das OpenRouter-Werkzeug `openrouter:web_search`: Hat der Hersteller eine
eigene Suche (OpenAI, Anthropic, Google, xAI, Perplexity), wird diese genutzt, sonst Exa. Die Kanäle über
OpenRouter laufen zusätzlich zu den direkt angebundenen; Sie können auch nur OpenRouter verwenden.

**1. Schlüssel anlegen** unter openrouter.ai → Settings → Keys und Guthaben aufladen.

**2. Auswahlskript starten** (im Projektordner, mit aktivierter Umgebung):

```bash
python openrouter_config.py
```

Es öffnet ein Menü:

```
Gewählte Modelle (Prüfung mit 22 Fragen, je Frage eine Antwort mit Websuche)

   Nr  Modell                           Token   Websuche   je Prüfung
    1  openai/gpt-5                    0,72 $     0,44 $       1,16 $
    2  anthropic/claude-opus-5.5       1,63 $     0,44 $       2,07 $
    3  perplexity/sonar                0,15 $     0,11 $       0,26 $
       Summe                                                   3,49 $

  1  Modell suchen und hinzufügen
  2  Modell entfernen
  3  Anzahl Fragen für die Schätzung ändern (derzeit 22)
  4  API-Schlüssel eintragen
  0  Beenden
```

- **4 – API-Schlüssel eintragen:** Der Schlüssel wird verdeckt eingegeben, bei OpenRouter geprüft und in
  `.env` gespeichert.
- **1 – Modell suchen und hinzufügen:** Suchbegriff eingeben (z. B. `claude`, `gpt`, `gemini flash`,
  `sonar`). Sie sehen die passenden Modelle mit den voraussichtlichen Kosten einer Prüfung und wählen sie
  über ihre Nummern aus (mehrere mit Leerzeichen getrennt). Modelle ohne Websuche sind markiert.
- **2 – Modell entfernen:** Nummer aus der Liste der gewählten Modelle eingeben.
- **3 – Anzahl Fragen:** Die Schätzung rechnet standardmäßig mit 22 Fragen (etwa 20 Fachfragen und zwei
  Fragen nach der Marke). Haben Sie mehr oder weniger Fragen, tragen Sie die Zahl hier ein.

Die Tabelle zeigt nur die **gewählten** Modelle: Kosten für Token und Websuche je Prüfung sowie die Summe.
Die Preise ruft das Skript bei jedem Start aktuell von OpenRouter ab (in US-Dollar). Die Schätzung nimmt je
Antwort etwa 6.000 Eingabe-Token an, denn auch die gelesenen Suchergebnisse zählen als Eingabe. Dazu
kommen etwa 1.000 Ausgabe-Token, bei Modellen mit Denkphase weitere 1.500, und zwei Websuchen (bei
Perplexity eine). Die echten Kosten schwanken mit Antwortlänge und Zahl der Suchen. Prüfen Sie sie nach
der ersten Messung unter openrouter.ai/activity.

**3. Peilung neu starten.** Danach unter **„Kanäle & Einstellungen“** je Modell die Testabfrage ausführen.

Dasselbe ohne Menü, z. B. für Skripte:

```bash
python openrouter_config.py liste                        # gewählte Modelle mit Kosten
python openrouter_config.py liste --fragen 30            # Schätzung für 30 Fragen
python openrouter_config.py suche claude opus            # Modelle suchen
python openrouter_config.py hinzu openai/gpt-5 perplexity/sonar
python openrouter_config.py entfernen openai/gpt-5       # oder die Nummer aus der Liste
python openrouter_config.py schluessel                   # Schlüssel eintragen
```

Die Auswahl steht in `.env` unter `OPENROUTER_MODELS` (durch Komma getrennt) und lässt sich dort auch von
Hand ändern. Weitere Einträge:

| Eintrag | Bedeutung |
|---|---|
| `OPENROUTER_SEARCH_ENGINE` | `auto` (Standard: eigene Suche des Herstellers, sonst Exa), `native`, `exa`, `parallel` oder `perplexity` |
| `OPENROUTER_ANALYSIS_MODEL` | Modell für die Auswertung über OpenRouter; leer = das erste gewählte Modell |
| `ANALYSIS_PROVIDER=openrouter` | Auswertung ausdrücklich über OpenRouter. Bei `auto` geschieht das nur, wenn kein anderer KI-Schlüssel eingetragen ist |

**Modelle wechseln und Vergleichbarkeit:** Ein neu gewähltes Modell erscheint ab der nächsten Prüfung. Ein
entferntes Modell wird nicht mehr abgefragt. In früheren Berichten und in den Verläufen bleibt es mit seinen
Ergebnissen erhalten. Die Gesamt-Trefferquote rechnet über alle in der jeweiligen Prüfung befragten Modelle.
Wenn Sie Modelle hinzufügen oder entfernen, verschiebt sich also die Grundlage des Vergleichs zur
Vorprüfung. Die Werte je Modell bleiben vergleichbar.

### Claude über das Claude-Abo (Claude Code)

Haben Sie ein Claude-Abo (Pro oder Max) und Claude Code installiert, kann Peilung Claude darüber befragen.
Ein API-Schlüssel ist dafür nicht nötig. Der Kanal heißt im Bericht **„Claude (Abo)“** und läuft
zusätzlich zum Kanal „Claude“ über die API.

1. Claude Code installieren (claude.com/claude-code). Einmal `claude` im Terminal starten und mit dem
   Abo anmelden.
2. In `.env` setzen:
   ```
   CLAUDE_CODE_MODE=on
   CLAUDE_CODE_MODEL=        # optional, z. B. opus oder sonnet; leer = Standard Ihres Kontos
   CLAUDE_CODE_PATH=claude   # nur ändern, wenn claude nicht im Suchpfad liegt
   ```
3. Peilung neu starten und unter „Kanäle & Einstellungen“ die Testabfrage ausführen.

So funktioniert es: Peilung startet je Frage `claude -p` im nicht-interaktiven Modus. Claude Code läuft dabei
abgeschottet: leeres Arbeitsverzeichnis, ohne Ihre Einstellungen, Plugins, Hooks und MCP-Server, und als
Werkzeug nur die Websuche. Ein gesetzter `ANTHROPIC_API_KEY` wird für diesen Aufruf ausgeblendet, damit
über das Abo abgerechnet wird und nicht über die API. Als Quellen gelten die Treffer der Websuche, die
Claude gelesen hat.

Zu beachten:
- Die Abfragen zählen gegen die **Nutzungsgrenzen Ihres Abos**. Eine Prüfung mit 22 Fragen sind 22
  Anfragen mit Websuche, höchstens zwei gleichzeitig. Ist das Kontingent erschöpft, schlagen die
  Abfragen fehl. Sie lassen sich auf der Seite des Laufs später erneut anstoßen.
- Das Abo ist für Ihren eigenen Gebrauch. Für ein Angebot an Kunden den Kanal „Claude“ mit API-Schlüssel
  verwenden.
- Mit `ANALYSIS_PROVIDER=claudecode` übernimmt das Abo auch die Auswertung. Bei `auto` geschieht das nur,
  wenn kein anderer KI-Schlüssel eingetragen ist.

### Google KI-Übersicht (Ihr eigener Chrome)

Der Kanal **„Google KI-Übersicht“** stellt jede Frage bei Google und liest die „Übersicht mit KI“ aus, die
Google über den Treffern zeigt. Er misst damit die KI-Antwort, die die meisten Menschen tatsächlich sehen.
Die Quellen sind die Links in der Übersicht. Zeigt Google keine Übersicht, gilt die Antwort als „nicht
genannt“.

**Empfohlen: über die Peilung-Erweiterung in Ihrem normalen Chrome.** Die Suchen laufen dann in dem Chrome,
mit dem Sie selbst googeln, mit Ihren Cookies und Ihrer Anmeldung. Ein frisches, unbekanntes Browserprofil
sperrt Google dagegen schnell mit einem Captcha.

1. In Chrome `chrome://extensions` öffnen und oben rechts den **Entwicklermodus** einschalten.
2. **„Entpackte Erweiterung laden“** klicken und den Ordner `chrome_extension` im Projektordner wählen.
3. In `.env` setzen: `GOOGLE_AI_MODE=extension`
4. Peilung neu starten. Unter „Kanäle & Einstellungen“ steht bei „Google KI-Übersicht“, ob die Erweiterung
   verbunden ist (das kann nach dem Start bis zu 30 Sekunden dauern). Dann die Testabfrage ausführen.

Die Erweiterung fragt Peilung unter `http://127.0.0.1:8000` nach Suchaufträgen. Läuft Peilung auf einem
anderen Port, die Adresse oben in `chrome_extension/background.js` anpassen und die Erweiterung neu laden.
Peilung nimmt die Ergebnisse nur vom eigenen Rechner und nur von einer Chrome-Erweiterung an, auch wenn ein
`APP_PASSWORD` gesetzt ist.

**Alternative ohne Erweiterung** (`GOOGLE_AI_MODE=on`): Peilung steuert ein zweites Chrome mit eigenem Profil
über das DevTools-Protokoll. Starten mit

```bash
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.peilung-chrome" --no-first-run
```

Unter Linux: `google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.peilung-chrome" &`.
In diesem Fenster einmal bei Google anmelden und ein Captcha lösen, sonst sperrt Google sofort.

Während einer Messung muss Chrome offen bleiben. Peilung öffnet je Frage kurz einen Hintergrund-Tab, liest
die Übersicht und schließt ihn wieder. Zwischen zwei Suchen liegen 2–4 Sekunden. Zeigt Google eine
Sperrseite (Captcha), wird die Abfrage sofort als Fehler markiert und nicht wiederholt. Lösen Sie dann das
Captcha im Fenster und stoßen Sie die Fragen auf der Seite des Laufs erneut an.

Hinweis: Automatisches Abfragen widerspricht den Nutzungsbedingungen von Google. Bei 20–25 Suchen pro
Prüfung im Tempo eines Menschen ist das Risiko einer Sperre gering, aber nicht ausgeschlossen.

### Optional: PDF-Export und Copilot

```bash
pip install playwright && playwright install chromium
```

Ohne Playwright funktioniert alles andere; den Bericht können Sie dann im Browser über „Drucken“ als PDF
speichern.

---

## Dauerbetrieb

- **Zeitplan:** Fällige Prüfungen startet Peilung selbst, solange das Programm läuft. Für einen Server oder
  Heimserver empfiehlt sich ein systemd-Dienst, der `python run.py` im Projektordner startet.
- **Zugriff von anderen Rechnern:** In `.env` `HOST=0.0.0.0` und ein `APP_PASSWORD` setzen. Die Oberfläche
  fragt dann nach dem Passwort (Benutzername beliebig). Für den Zugang aus dem Internet einen Reverse-Proxy
  mit HTTPS davorschalten.
- **Daten:** Alles liegt in `data/peilung.db`. Zum Sichern genügt es, diese Datei zu kopieren, während das
  Programm beendet ist.
- **Unterbrechungen:** Nach einem Neustart setzt Peilung angefangene Läufe fort. Fehlgeschlagene Abfragen
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
| `app/channels.py`, `app/llm.py` | Die Messkanäle (inkl. OpenRouter, Claude-Abo, Google KI-Übersicht), Auswertungsmodell, Demo-Antworten |
| `openrouter_config.py` | OpenRouter-Modelle auswählen und entfernen, Kosten einer Prüfung schätzen |
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

Änderungen je Version: [CHANGELOG.md](CHANGELOG.md)
