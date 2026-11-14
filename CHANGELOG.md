# Änderungen

## Unveröffentlicht

- Projekt von „Peilung“ in „AI-Visibility“ umbenannt (Oberfläche, Berichte, Dokumentation, Code).
  Die Datenbank heißt jetzt standardmäßig `data/ai-visibility.db`; bestehende `data/peilung.db` umbenennen
  oder `DB_PATH` in `.env` setzen.

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
