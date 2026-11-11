"""Konfiguration aus Umgebungsvariablen bzw. der Datei .env."""
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()


def env(key, default=""):
    return os.environ.get(key, default).strip()


def demo_mode():
    return env("DEMO_MODE", "0") in ("1", "true", "yes")


def db_path():
    p = Path(env("DB_PATH", "data/peilung.db"))
    return p if p.is_absolute() else ROOT / p


MAX_PAGES = int(env("MAX_PAGES", "150") or 150)
USER_AGENT = "Mozilla/5.0 (compatible; PeilungBot/0.1; Website-Audit)"


def openrouter_models():
    """Die über OpenRouter zu prüfenden Modelle (OPENROUTER_MODELS, durch Komma getrennt)."""
    return list(dict.fromkeys(m.strip() for m in env("OPENROUTER_MODELS").split(",") if m.strip()))


def openrouter_key(model):
    """Kanalschlüssel eines OpenRouter-Modells, z. B. openai/gpt-5 -> or-openai-gpt-5."""
    return "or-" + re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


# Reihenfolge = Reihenfolge im Bericht. "ai" = KI-Modell, "web" = klassische Websuche.
# Über OpenRouter gewählte Modelle sind eigene KI-Kanäle und stehen vor der Websuche.
CHANNELS = [
    {"key": "chatgpt", "label": "ChatGPT", "kind": "ai"},
    {"key": "gemini", "label": "Gemini", "kind": "ai"},
    {"key": "perplexity", "label": "Perplexity", "kind": "ai"},
    {"key": "claude", "label": "Claude", "kind": "ai"},
] + ([{"key": "claudecode", "label": "Claude (Abo)", "kind": "ai"}] if env("CLAUDE_CODE_MODE", "off") == "on" else []) + [
    {"key": "copilot", "label": "Copilot", "kind": "ai"},
] + ([{"key": "google_ai", "label": "Google KI-Übersicht", "kind": "ai"}]
     if env("GOOGLE_AI_MODE", "off") in ("extension", "on") else []) \
  + [{"key": openrouter_key(m), "label": m, "kind": "ai", "model": m} for m in openrouter_models()] \
  + ([] if env("SEARCH_PROVIDER", "duckduckgo") == "off" else [{"key": "web", "label": "Websuche", "kind": "web"}])
OPENROUTER_CHANNELS = {c["key"]: c["model"] for c in CHANNELS if "model" in c}
AI_CHANNELS = [c["key"] for c in CHANNELS if c["kind"] == "ai"]
CHANNEL_LABEL = {c["key"]: c["label"] for c in CHANNELS}


def channel_status():
    """Welche Kanäle sind messbereit? -> {key: (bereit, Hinweis)}"""
    if demo_mode():
        return {c["key"]: (True, "simuliert (Demo-Modus)") for c in CHANNELS}
    s = {}
    for key, var, model_var in [
        ("chatgpt", "OPENAI_API_KEY", "OPENAI_MODEL"),
        ("gemini", "GEMINI_API_KEY", "GEMINI_MODEL"),
        ("perplexity", "PERPLEXITY_API_KEY", "PERPLEXITY_MODEL"),
        ("claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
    ]:
        s[key] = (True, f"Modell {env(model_var)}") if env(var) else (False, f"{var} fehlt")
    for key in OPENROUTER_CHANNELS:
        s[key] = (True, f"über OpenRouter, Websuche {env('OPENROUTER_SEARCH_ENGINE', 'auto')}") \
            if env("OPENROUTER_API_KEY") else (False, "OPENROUTER_API_KEY fehlt")
    if "claudecode" in CHANNEL_LABEL:
        s["claudecode"] = (True, f"Claude Code mit Ihrem Abo, Modell {env('CLAUDE_CODE_MODEL') or 'Standard des Kontos'}") \
            if claude_code_path() else (False, "Programm claude nicht gefunden (CLAUDE_CODE_PATH)")
    mode = env("COPILOT_MODE", "off")
    s["copilot"] = (True, "Browser-Fernsteuerung (experimentell)") if mode == "browser" else (
        False, "COPILOT_MODE=off")
    if "google_ai" in CHANNEL_LABEL:
        from . import bridge
        if env("GOOGLE_AI_MODE") == "extension":
            s["google_ai"] = (True, "Ihr Chrome über die Peilung-Erweiterung" + (
                "" if bridge.connected() else " – derzeit nicht verbunden, Chrome öffnen"))
        else:
            s["google_ai"] = (True, f"Chrome mit Fernsteuerung unter {env('GOOGLE_CDP_URL', 'http://127.0.0.1:9222')}")
    prov = env("SEARCH_PROVIDER", "duckduckgo")
    if prov == "off":
        pass
    elif prov == "brave":
        s["web"] = (True, "Brave Search") if env("BRAVE_API_KEY") else (False, "BRAVE_API_KEY fehlt")
    else:
        s["web"] = (True, "DuckDuckGo (ohne Schlüssel)")
    return s


def claude_code_path():
    """Pfad zur Claude-Code-Kommandozeile oder None."""
    return shutil.which(env("CLAUDE_CODE_PATH", "claude") or "claude")


def openrouter_analysis_model():
    """Modell für die Auswertung über OpenRouter: OPENROUTER_ANALYSIS_MODEL, sonst das erste gewählte."""
    return env("OPENROUTER_ANALYSIS_MODEL") or next(iter(openrouter_models()), "")


def analysis_provider():
    """Anbieter für die Auswertung oder None."""
    want = env("ANALYSIS_PROVIDER", "auto")
    keys = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY", "perplexity": "PERPLEXITY_API_KEY", "openrouter": "OPENROUTER_API_KEY",
            "claudecode": None}

    def usable(p):
        if p == "claudecode":
            return env("CLAUDE_CODE_MODE", "off") == "on" and bool(claude_code_path())
        return bool(env(keys[p])) and (p != "openrouter" or bool(openrouter_analysis_model()))

    if want in keys:
        return want if usable(want) else None
    for p in keys:
        if usable(p):
            return p
    return None
