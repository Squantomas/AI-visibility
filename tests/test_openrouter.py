"""Tests: OpenRouter-Kanäle, Auswahl- und Kostenskript."""
from tests.test_core import PORT  # noqa: F401  (Umgebung, Test-Website und Datenbank einrichten)

import openrouter_config as orc
from app import config, llm, measure, questions, report

MODEL = "acme/sucher-1"
KEY = config.openrouter_key(MODEL)


def test_channel_key_is_url_safe():
    assert config.openrouter_key("anthropic/claude-opus-5.5") == "or-anthropic-claude-opus-5-5"
    assert config.openrouter_key("~openai/gpt-latest:free") == "or-openai-gpt-latest-free"


def test_openrouter_answer_and_citations(monkeypatch):
    sent = {}

    def fake_post(url, headers, body):
        sent.update(url=url, body=body)
        return {"choices": [{"message": {"content": "Anbieter A und B.", "annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://a.example/"}},
            {"type": "url_citation", "url_citation": {"url": "https://a.example/"}},
            {"type": "url_citation", "url_citation": {"url": "https://b.example/x"}}]}}]}

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(llm, "_post", fake_post)
    text, cites = llm.openrouter("Wer liefert Filter?", web=True, model=MODEL)
    assert text == "Anbieter A und B." and cites == ["https://a.example/", "https://b.example/x"]
    assert sent["url"].endswith("/chat/completions") and sent["body"]["model"] == MODEL
    assert sent["body"]["tools"][0]["type"] == "openrouter:web_search"
    llm.openrouter("Auswertung", system="JSON", model=MODEL)
    assert "tools" not in sent["body"] and sent["body"]["messages"][0]["role"] == "system"


def test_cost_estimate():
    m = {"id": "acme/x", "supported_parameters": ["tools", "reasoning"],
         "pricing": {"prompt": "0.000001", "completion": "0.00001", "web_search": "0.01"}}
    e = orc.estimate(m, fragen=10)
    per = orc.TOKENS_IN * 1e-6 + (orc.TOKENS_OUT + orc.TOKENS_DENKEN) * 1e-5 + orc.SUCHEN * 0.01
    assert abs(e["answer"] - per) < 1e-9 and abs(e["check"] - 10 * per) < 1e-9
    # ohne eigene Suche gilt der Exa-Preis, ohne Werkzeuge gibt es keine Suche
    assert orc.estimate({**m, "pricing": {"prompt": "0", "completion": "0"}})["search"] == orc.FRAGEN * orc.SUCHEN * orc.EXA_PREIS
    assert orc.estimate({**m, "supported_parameters": []}, 1)["search"] == 0
    assert orc.estimate({**m, "pricing": {"prompt": "-1", "completion": "-1"}}) is None
    assert orc.usd(1234.5) == "1.234,50 $"


def test_select_and_remove_models(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# Kommentar\nDEMO_MODE=0\nOPENROUTER_MODELS=\n", encoding="utf-8")
    monkeypatch.setattr(orc, "ENV_FILE", f)
    monkeypatch.setattr(orc, "catalog", lambda: {i: {"id": i, "pricing": {}} for i in ("a/x", "b/y", "c/z")})
    orc.add(["a/x", "b/y", "c/z", "a/x", "nicht/da"])
    assert orc.selected() == ["a/x", "b/y", "c/z"]
    orc.remove(["2", "c/z"])
    assert orc.selected() == ["a/x"]
    orc.set_env("OPENROUTER_API_KEY", "sk-or-1")
    text = f.read_text(encoding="utf-8")
    assert text.startswith("# Kommentar\nDEMO_MODE=0\nOPENROUTER_MODELS=a/x\n") and "OPENROUTER_API_KEY=sk-or-1" in text


def test_model_added_then_removed(monkeypatch):
    """Ein gewähltes Modell wird gemessen; nach dem Entfernen bleibt es in alten Berichten erhalten."""
    chans = config.CHANNELS[:-1] + [{"key": KEY, "label": MODEL, "kind": "ai", "model": MODEL}] + config.CHANNELS[-1:]
    monkeypatch.setattr(config, "CHANNELS", chans)
    monkeypatch.setattr(config, "OPENROUTER_CHANNELS", {KEY: MODEL})
    monkeypatch.setattr(config, "CHANNEL_LABEL", {c["key"]: c["label"] for c in chans})
    sid = questions.create_site(f"http://localhost:{PORT}", "Brückner Filtertechnik", "none")
    questions.analyse_site(sid)
    r1 = measure.enqueue(sid)
    measure.execute(r1)
    R1 = report.build(r1)
    n = R1["head"]["questions"]
    assert R1["head"]["ai"][1] == n * 6 and [m["key"] for m in R1["models"]][-2:] == [KEY, "web"]
    assert all(m["measured"] for m in R1["models"])

    # Modell entfernen: neuer Lauf ohne das Modell, alter Bericht unverändert
    base = [c for c in chans if c["key"] != KEY]
    monkeypatch.setattr(config, "CHANNELS", base)
    monkeypatch.setattr(config, "OPENROUTER_CHANNELS", {})
    monkeypatch.setattr(config, "CHANNEL_LABEL", {c["key"]: c["label"] for c in base})
    r2 = measure.enqueue(sid)
    measure.execute(r2)
    R2 = report.build(r2)
    assert KEY not in [m["key"] for m in R2["models"]] and R2["head"]["ai"][1] == n * 5
    assert MODEL in [c["label"] for c in R2["trends"]["channels"]]  # Verlauf zeigt das Modell bis zum Entfernen
    R1b = report.build(r1)
    assert R1b["head"] == R1["head"] and MODEL in [m["label"] for m in R1b["models"]]
