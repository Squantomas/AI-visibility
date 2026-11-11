"""OpenRouter-Modelle für die Messung auswählen und die Kosten einer Prüfung schätzen.

    python openrouter_config.py                      Menü
    python openrouter_config.py liste                gewählte Modelle mit voraussichtlichen Kosten
    python openrouter_config.py suche claude opus    Modelle suchen (alle Wörter müssen passen)
    python openrouter_config.py hinzu openai/gpt-5 anthropic/claude-opus-5.5
    python openrouter_config.py entfernen openai/gpt-5      (oder die Nummer aus der Liste)
    python openrouter_config.py schluessel           API-Schlüssel eintragen (verdeckte Eingabe)

Option --fragen N: Fragen je Prüfung für die Kostenschätzung (Standard 22: etwa 20 Fachfragen und zwei
Fragen nach der Marke). Die Auswahl steht in der Datei .env unter OPENROUTER_MODELS.
"""
import argparse
import getpass
import re
import shutil
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
API = "https://openrouter.ai/api/v1"

# Annahmen für die Schätzung je Antwort. Gelesene Suchergebnisse zählen als Eingabe-Token.
FRAGEN = 22
TOKENS_IN = 6000
TOKENS_OUT = 1000
TOKENS_DENKEN = 1500   # nur bei Modellen mit Denkphase ("reasoning")
SUCHEN = 2             # Suchanfragen je Antwort; Peilung erlaubt höchstens drei
EXA_PREIS = 0.007      # je Suche, wenn das Modell keine eigene Suche hat (OpenRouter-Preis für Exa)


# ---------- .env lesen und schreiben ----------

def env_values(path=None):
    path = path or ENV_FILE
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def set_env(key, value, path=None):
    """Setzt KEY=value in der .env; alle übrigen Zeilen und Kommentare bleiben unverändert."""
    path = path or ENV_FILE
    if not path.exists():
        example = path.with_name(".env.example")
        if example.exists():
            shutil.copy(example, path)
        else:
            path.write_text("", encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pat.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def selected(path=None):
    return list(dict.fromkeys(m.strip() for m in env_values(path).get("OPENROUTER_MODELS", "").split(",") if m.strip()))


def save_selected(models, path=None):
    set_env("OPENROUTER_MODELS", ",".join(models), path)


# ---------- Modellliste und Preise von OpenRouter ----------

_catalog = None


def catalog():
    """{id: Modell} aller Modelle, die über die Chat-Schnittstelle Text liefern. Die Liste ist öffentlich."""
    global _catalog
    if _catalog is None:
        try:
            r = httpx.get(f"{API}/models", timeout=30)
            r.raise_for_status()
        except httpx.HTTPError as e:
            sys.exit(f"Modellliste von OpenRouter nicht abrufbar ({e}). Bitte Internetverbindung prüfen.")
        _catalog = {m["id"]: m for m in r.json().get("data", [])
                    if "text" in (m.get("architecture") or {}).get("output_modalities", ["text"])
                    and "/api/v1/chat/completions" in m.get("endpoints", ["/api/v1/chat/completions"])}
    return _catalog


def has_search(m):
    """Kann das Modell im Web suchen? Perplexity sucht immer, sonst braucht es Werkzeugaufrufe."""
    return m["id"].startswith("perplexity/") or "tools" in m.get("supported_parameters", [])


def estimate(m, fragen=FRAGEN):
    """Voraussichtliche Kosten in USD: {"answer", "tokens", "search", "check"} oder None bei variablem Preis."""
    p = m.get("pricing") or {}
    try:
        price = {k: float(v) for k, v in p.items() if k != "overrides" and v not in (None, "")}
    except (TypeError, ValueError):
        return None
    if any(v < 0 for v in price.values()):  # Router-Modelle ohne festen Preis
        return None
    tokens = TOKENS_IN * price.get("prompt", 0) + TOKENS_OUT * price.get("completion", 0)
    if "reasoning" in m.get("supported_parameters", []):
        tokens += TOKENS_DENKEN * price.get("internal_reasoning", price.get("completion", 0))
    searches = 1 if m["id"].startswith("perplexity/") else SUCHEN
    search = searches * (price.get("web_search") or EXA_PREIS) if has_search(m) else 0
    answer = tokens + search + price.get("request", 0)
    return {"answer": answer, "tokens": tokens * fragen, "search": search * fragen, "check": answer * fragen}


def usd(x, digits=2):
    return f"{x:,.{digits}f} $".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------- Ausgabe ----------

def show_selected(fragen):
    models = selected()
    print(f"\nGewählte Modelle (Prüfung mit {fragen} Fragen, je Frage eine Antwort mit Websuche)\n")
    if not models:
        print("  noch keine – mit „Modell suchen und hinzufügen“ bzw. `hinzu <modell>` auswählen.\n")
        return models
    cat = catalog()
    w = max(len(m) for m in models) + 2
    print(f"  {'Nr':>3}  {'Modell':<{w}}{'Token':>11}{'Websuche':>11}{'je Prüfung':>13}")
    total = 0.0
    unknown = []
    for i, mid in enumerate(models, 1):
        m = cat.get(mid)
        e = estimate(m, fragen) if m else None
        if e is None:
            unknown.append(mid)
            note = "nicht mehr bei OpenRouter" if not m else "Preis variabel"
            print(f"  {i:>3}  {mid:<{w}}{note:>35}")
            continue
        total += e["check"]
        flag = "" if has_search(m) else "   ohne Websuche!"
        print(f"  {i:>3}  {mid:<{w}}{usd(e['tokens']):>11}{usd(e['search']):>11}{usd(e['check']):>13}{flag}")
    print(f"  {'':>3}  {'Summe':<{w}}{'':>22}{usd(total):>13}")
    n = lambda x: f"{x:,}".replace(",", ".")  # noqa: E731
    print(f"\n  Annahmen je Antwort: ~{n(TOKENS_IN)} Eingabe- und ~{n(TOKENS_OUT)} Ausgabe-Token (+{n(TOKENS_DENKEN)} "
          f"Denk-Token bei Modellen mit Denkphase), {SUCHEN} Websuchen (Perplexity: eine).")
    print("  Tatsächliche Kosten schwanken je nach Antwortlänge und Zahl der Suchen; nach der ersten Messung")
    print("  unter openrouter.ai/activity prüfen.")
    if unknown:
        print(f"  Ohne Schätzung: {', '.join(unknown)}")
    vals = env_values()
    if not vals.get("OPENROUTER_API_KEY"):
        print("  Hinweis: OPENROUTER_API_KEY fehlt noch (Befehl `schluessel`).")
    if analysis_via_openrouter(vals):
        print(f"  Hinweis: Auch die Auswertung läuft über OpenRouter "
              f"({vals.get('OPENROUTER_ANALYSIS_MODEL') or models[0]}); deren Kosten sind nicht enthalten.")
    print()
    return models


def analysis_via_openrouter(vals):
    want = vals.get("ANALYSIS_PROVIDER", "auto") or "auto"
    if want == "openrouter":
        return True
    others = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "PERPLEXITY_API_KEY")
    return want == "auto" and bool(vals.get("OPENROUTER_API_KEY")) and not any(vals.get(k) for k in others)


def search(words, fragen, limit=25):
    words = [w.lower() for w in words]
    hits = [m for mid, m in sorted(catalog().items()) if not mid.endswith(":batch")
            and all(w in (mid + " " + m.get("name", "")).lower() for w in words)]
    print(f"\n{len(hits)} Modelle gefunden" + (f", die ersten {limit}:" if len(hits) > limit else ":") + "\n")
    hits = hits[:limit]
    if hits:
        w = max(len(m["id"]) for m in hits) + 2
        print(f"  {'Nr':>3}  {'Modell':<{w}}{'je Prüfung':>13}  Hinweis")
        mine = set(selected())
        for i, m in enumerate(hits, 1):
            e = estimate(m, fragen)
            notes = ["gewählt"] if m["id"] in mine else []
            notes += [] if has_search(m) else ["keine Websuche"]
            print(f"  {i:>3}  {m['id']:<{w}}{(usd(e['check']) if e else 'variabel'):>13}  {', '.join(notes)}")
    print()
    return hits


def add(ids):
    cat, models = catalog(), selected()
    for mid in ids:
        mid = mid.strip()
        if mid in models:
            print(f"  {mid}: bereits gewählt")
        elif mid not in cat:
            print(f"  {mid}: unbekannt – genaue Kennung mit `suche` ermitteln")
        else:
            models.append(mid)
            print(f"  {mid}: hinzugefügt" + ("" if has_search(cat[mid]) else
                                           " (Achtung: unterstützt keine Websuche, Antworten nur aus dem Training)"))
    save_selected(models)


def remove(items):
    models = selected()
    drop = set()
    for it in items:
        it = it.strip()
        if it.isdigit() and 1 <= int(it) <= len(models):
            drop.add(models[int(it) - 1])
        elif it in models:
            drop.add(it)
        else:
            print(f"  {it}: nicht in der Auswahl")
    for mid in drop:
        print(f"  {mid}: entfernt")
    save_selected([m for m in models if m not in drop])


def set_key():
    old = env_values().get("OPENROUTER_API_KEY", "")
    print(f"Derzeit: {mask(old) if old else 'kein Schlüssel'}")
    key = getpass.getpass("Neuer OpenRouter-Schlüssel (Eingabe unsichtbar, Enter = unverändert): ").strip()
    if not key:
        return
    try:
        r = httpx.get(f"{API}/key", headers={"Authorization": f"Bearer {key}"}, timeout=20)
        if r.status_code == 401:
            if not ask_yes("OpenRouter kennt diesen Schlüssel nicht. Trotzdem speichern?"):
                return
        elif r.status_code < 400:
            d = r.json().get("data", {})
            limit = d.get("limit")
            print(f"Schlüssel gültig. Bisher verbraucht: {usd(d.get('usage') or 0)}"
                  + (f", Limit: {usd(limit)}" if limit is not None else ""))
    except httpx.HTTPError:
        print("Schlüssel konnte nicht geprüft werden (keine Verbindung); er wird trotzdem gespeichert.")
    set_env("OPENROUTER_API_KEY", key)
    print("Gespeichert in .env.")


def mask(key):
    return key[:6] + "…" + key[-4:] if len(key) > 12 else "gesetzt"


def ask_yes(q):
    return input(f"{q} [j/N] ").strip().lower() in ("j", "ja", "y", "yes")


def split_input(text):
    return [x for x in re.split(r"[,\s]+", text) if x]


RESTART = "Damit die Änderung wirkt, Peilung neu starten (python run.py)."


def menu(fragen):
    while True:
        key = env_values().get("OPENROUTER_API_KEY", "")
        print("=" * 70 + "\nPeilung · OpenRouter-Modelle" + f"   (Schlüssel: {mask(key) if key else 'fehlt'})")
        models = show_selected(fragen)
        print("  1  Modell suchen und hinzufügen\n  2  Modell entfernen\n"
              f"  3  Anzahl Fragen für die Schätzung ändern (derzeit {fragen})\n  4  API-Schlüssel eintragen\n"
              "  0  Beenden")
        choice = input("\nAuswahl: ").strip()
        if choice in ("0", "q", ""):
            return
        if choice == "1":
            words = split_input(input("Suchbegriff (z. B. gpt, claude, gemini, sonar): "))
            hits = search(words, fragen) if words else []
            if hits:
                picks = split_input(input("Nummern oder Kennungen zum Hinzufügen (z. B. 1 3), Enter = keine: "))
                ids = [hits[int(p) - 1]["id"] if p.isdigit() and 1 <= int(p) <= len(hits) else p for p in picks]
                if ids:
                    add(ids)
                    print(RESTART)
        elif choice == "2" and models:
            picks = split_input(input("Nummern der zu entfernenden Modelle (z. B. 2), Enter = keine: "))
            if picks:
                remove(picks)
                print(RESTART)
        elif choice == "3":
            try:
                fragen = max(1, int(input("Fragen je Prüfung: ").strip()))
            except ValueError:
                print("Bitte eine Zahl eingeben.")
        elif choice == "4":
            set_key()


def main(argv=None):
    ap = argparse.ArgumentParser(description="OpenRouter-Modelle für Peilung auswählen und Kosten schätzen.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("befehl", nargs="?", choices=["liste", "suche", "hinzu", "entfernen", "schluessel"])
    ap.add_argument("werte", nargs="*", help="Suchbegriffe, Modellkennungen oder Nummern")
    ap.add_argument("--fragen", type=int, default=FRAGEN, help=f"Fragen je Prüfung (Standard {FRAGEN})")
    a = ap.parse_args(argv)
    fragen = max(1, a.fragen)
    try:
        if a.befehl is None:
            menu(fragen)
        elif a.befehl == "liste":
            show_selected(fragen)
        elif a.befehl == "suche":
            search(a.werte, fragen)
        elif a.befehl in ("hinzu", "entfernen"):
            if not a.werte:
                ap.error(f"{a.befehl}: mindestens ein Modell angeben")
            (add if a.befehl == "hinzu" else remove)(a.werte)
            show_selected(fragen)
            print(RESTART)
        elif a.befehl == "schluessel":
            set_key()
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
