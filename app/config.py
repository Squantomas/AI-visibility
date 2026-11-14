"""Konfiguration aus Umgebungsvariablen bzw. der Datei .env."""
import os
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
    p = Path(env("DB_PATH", "data/ai-visibility.db"))
    return p if p.is_absolute() else ROOT / p


MAX_PAGES = int(env("MAX_PAGES", "150") or 150)
USER_AGENT = "Mozilla/5.0 (compatible; AI-VisibilityBot/0.1; Website-Audit)"

# Reihenfolge = Reihenfolge im Bericht. "ai" = KI-Modell, "web" = klassische Websuche.
CHANNELS = [
    {"key": "chatgpt", "label": "ChatGPT", "kind": "ai"},
    {"key": "gemini", "label": "Gemini", "kind": "ai"},
    {"key": "perplexity", "label": "Perplexity", "kind": "ai"},
    {"key": "claude", "label": "Claude", "kind": "ai"},
    {"key": "copilot", "label": "Copilot", "kind": "ai"},
    {"key": "web", "label": "Websuche", "kind": "web"},
]
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
    mode = env("COPILOT_MODE", "off")
    s["copilot"] = (True, "Browser-Fernsteuerung (experimentell)") if mode == "browser" else (
        False, "COPILOT_MODE=off")
    prov = env("SEARCH_PROVIDER", "duckduckgo")
    if prov == "brave":
        s["web"] = (True, "Brave Search") if env("BRAVE_API_KEY") else (False, "BRAVE_API_KEY fehlt")
    else:
        s["web"] = (True, "DuckDuckGo (ohne Schlüssel)")
    return s


def analysis_provider():
    """Anbieter für die Auswertung oder None."""
    want = env("ANALYSIS_PROVIDER", "auto")
    keys = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY", "perplexity": "PERPLEXITY_API_KEY"}
    if want in keys:
        return want if env(keys[want]) else None
    for p, var in keys.items():
        if env(var):
            return p
    return None
