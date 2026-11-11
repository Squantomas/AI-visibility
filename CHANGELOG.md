# Änderungen

## Unveröffentlicht

- Weitere Modelle über OpenRouter: Jedes gewählte Modell ist ein eigener Kanal mit Websuche
  (`openrouter:web_search`). Neue Einträge `OPENROUTER_API_KEY`, `OPENROUTER_MODELS`,
  `OPENROUTER_SEARCH_ENGINE` und `OPENROUTER_ANALYSIS_MODEL`. OpenRouter kann auch die Auswertung übernehmen.
- Neues Skript `openrouter_config.py`: Modelle suchen, hinzufügen und entfernen, Schlüssel eintragen und
  die voraussichtlichen Kosten einer Prüfung für die gewählten Modelle anzeigen.
- Neuer Kanal „Claude (Abo)“ (`CLAUDE_CODE_MODE=on`): befragt Claude über die Kommandozeile von Claude Code
  mit dem eigenen Claude-Abo statt API-Schlüssel, abgeschottet und nur mit Websuche.
- Neuer Kanal „Google KI-Übersicht“ (`GOOGLE_AI_MODE=on`): stellt die Fragen in einem ferngesteuerten
  Chrome auf dem eigenen Rechner und liest die „Übersicht mit KI“ samt Quellen aus.
- Websuche abschaltbar mit `SEARCH_PROVIDER=off`.
- Fix: Empfehlungen stürzten ab, wenn ein neuer Kanal (OpenRouter, Claude-Abo) das schwächste Modell war.
- Websites löschen: gut sichtbarer Kasten auf der Website-Seite; gesperrt, solange eingelesen oder gemessen wird.
- Fix: Absturz beim Einlesen von Seiten mit Bildern in Kopf-, Fuß- oder Navigationsbereich.
- Berichte zeigen die Kanäle, die in der jeweiligen Prüfung befragt wurden. Entfernte Modelle bleiben in
  älteren Berichten und in den Verläufen erhalten.

## 0.1.0 – 2026-11-11

Erste Version.

- Website einlesen und etwa 20 Fragen in Themenfeldern vorschlagen; Fragen und Felder vor und zwischen
  den Prüfungen pflegen, mit Änderungsprotokoll.
- Messung über ChatGPT, Gemini, Perplexity, Claude, Copilot (experimentell) und eine Websuche.
- Automatische Erkennung der genannten Anbieter; Anbieterliste je Website bereinigen.
- Technische Prüfung der Website mit zwölf Prüfpunkten.
- Bericht als Webseite und PDF: Trefferquote je Kanal, Ergebnis je Frage und Kanal, Anbieteranteile je
  Themenfeld, Quellen, mindestens fünf priorisierte Empfehlungen, Veränderung zur Vorprüfung, Verläufe.
- Wiederholungsrhythmus je Website mit automatischer Zeitplanung.
- Demo-Modus mit simulierten Antworten und einer lokalen Test-Website.
