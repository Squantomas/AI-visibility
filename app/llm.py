"""Zugriff auf die Sprachmodelle: einmal als Messkanal (mit Websuche), einmal für die Auswertung (JSON)."""
import json
import re
import time

import httpx

from .config import env, openrouter_analysis_model

TIMEOUT = 180


class ChannelError(Exception):
    pass


def retry(fn, attempts=3):
    """Vorübergehende Fehler (Netz, 429, 5xx) mit wachsender Pause wiederholen."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            msg = str(e)
            permanent = any(code in msg for code in (" 400", " 401", " 403", " 404")) or isinstance(e, NotConfigured)
            if permanent or i == attempts - 1:
                break
            time.sleep(float(env("RETRY_PAUSE", "3")) * 3 ** i)
    raise ChannelError(f"{last.__class__.__name__}: {last}"[:500])


class NotConfigured(Exception):
    pass


def _post(url, headers, body):
    r = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:300]}")
    return r.json()


# ---------- Claude (offizielles Anthropic-SDK) ----------

def claude(prompt, system=None, web=False):
    import anthropic

    if not env("ANTHROPIC_API_KEY"):
        raise NotConfigured("ANTHROPIC_API_KEY fehlt")
    client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"), timeout=TIMEOUT, max_retries=1)
    kwargs = {"model": env("ANTHROPIC_MODEL", "claude-opus-5-5"), "max_tokens": 16000}
    if system:
        kwargs["system"] = system
    if web:
        kwargs["tools"] = [{"type": env("ANTHROPIC_WEB_TOOL", "web_search_20260209"), "name": "web_search",
                            "max_uses": 5,
                            "user_location": {"type": "approximate", "country": env("SEARCH_COUNTRY", "de").upper()}}]
    use_fallback = env("ANTHROPIC_FALLBACKS", "1") == "1"
    messages = [{"role": "user", "content": prompt}]
    text, cites = [], []
    for _ in range(5):
        try:
            if use_fallback:
                # Lehnt ein Sicherheitsfilter die Anfrage ab, beantwortet sie ein Ersatzmodell.
                resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                   fallbacks="default", messages=messages, **kwargs)
            else:
                resp = client.messages.create(messages=messages, **kwargs)
        except anthropic.AuthenticationError as e:
            raise RuntimeError(f"HTTP 401 {e}")
        except anthropic.BadRequestError as e:
            raise RuntimeError(f"HTTP 400 {e}")
        except anthropic.RateLimitError as e:
            raise RuntimeError(f"HTTP 429 {e}")
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"HTTP {e.status_code} {e}")
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"Verbindung fehlgeschlagen: {e}")
        if resp.stop_reason == "refusal":
            raise RuntimeError("Anfrage vom Modell abgelehnt (refusal)")
        for block in resp.content:
            if block.type == "text":
                text.append(block.text)
                for c in getattr(block, "citations", None) or []:
                    url = getattr(c, "url", None)
                    if url:
                        cites.append(url)
        if resp.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": resp.content})
    return "".join(text).strip(), list(dict.fromkeys(cites))


# ---------- OpenAI, Gemini, Perplexity (REST) ----------

def openai(prompt, system=None, web=False):
    if not env("OPENAI_API_KEY"):
        raise NotConfigured("OPENAI_API_KEY fehlt")
    body = {"model": env("OPENAI_MODEL", "gpt-5"), "input": prompt}
    if system:
        body["instructions"] = system
    if web:
        body["tools"] = [{"type": "web_search"}]
    data = _post("https://api.openai.com/v1/responses", {"Authorization": "Bearer " + env("OPENAI_API_KEY")}, body)
    text, cites = [], []
    for item in data.get("output", []):
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text":
                text.append(part.get("text", ""))
                cites += [a["url"] for a in part.get("annotations", []) if a.get("url")]
    return "".join(text).strip(), list(dict.fromkeys(cites))


def gemini(prompt, system=None, web=False):
    if not env("GEMINI_API_KEY"):
        raise NotConfigured("GEMINI_API_KEY fehlt")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if web:
        body["tools"] = [{"google_search": {}}]
    model = env("GEMINI_MODEL", "gemini-2.5-flash")
    data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                 {"x-goog-api-key": env("GEMINI_API_KEY")}, body)
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    cites = []
    for ch in cand.get("groundingMetadata", {}).get("groundingChunks", []):
        web_ = ch.get("web", {})
        uri, title = web_.get("uri", ""), web_.get("title", "")
        # Gemini liefert Weiterleitungsadressen; der Titel enthält meist die eigentliche Domain.
        if "vertexaisearch" in uri and re.fullmatch(r"[\w.-]+\.[a-z]{2,}", title or ""):
            uri = "https://" + title
        if uri:
            cites.append(uri)
    return text.strip(), list(dict.fromkeys(cites))


def perplexity(prompt, system=None, web=True):
    if not env("PERPLEXITY_API_KEY"):
        raise NotConfigured("PERPLEXITY_API_KEY fehlt")
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    data = _post("https://api.perplexity.ai/chat/completions",
                 {"Authorization": "Bearer " + env("PERPLEXITY_API_KEY")},
                 {"model": env("PERPLEXITY_MODEL", "sonar"), "messages": msgs})
    text = data["choices"][0]["message"]["content"]
    cites = list(data.get("citations") or []) or [r.get("url") for r in data.get("search_results", []) if r.get("url")]
    return text.strip(), list(dict.fromkeys(cites))


# ---------- OpenRouter: viele Modelle über eine Schnittstelle ----------

def openrouter(prompt, system=None, web=False, model=None):
    if not env("OPENROUTER_API_KEY"):
        raise NotConfigured("OPENROUTER_API_KEY fehlt")
    model = model or openrouter_analysis_model()
    if not model:
        raise NotConfigured("Kein OpenRouter-Modell gewählt")
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = {"model": model, "messages": msgs}
    if web:
        # Websuche als Server-Tool: das Modell entscheidet selbst, ob und wie oft es sucht.
        # "auto" nutzt die eingebaute Suche des Herstellers, wo es sie gibt, sonst Exa.
        body["tools"] = [{"type": "openrouter:web_search", "parameters": {
            "engine": env("OPENROUTER_SEARCH_ENGINE", "auto"), "max_results": 5, "max_uses": 3,
            "max_total_results": 15,
            "user_location": {"type": "approximate", "country": env("SEARCH_COUNTRY", "de").upper()}}}]
    data = _post("https://openrouter.ai/api/v1/chat/completions",
                 {"Authorization": "Bearer " + env("OPENROUTER_API_KEY"), "X-Title": "Peilung"}, body)
    if data.get("error"):
        raise RuntimeError(f"OpenRouter: {data['error']}"[:400])
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):  # manche Modelle liefern die Antwort in Teilen
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    cites = []
    for a in msg.get("annotations") or []:
        url = (a.get("url_citation") or {}).get("url") or a.get("url")
        if url:
            cites.append(url)
    return content.strip(), list(dict.fromkeys(cites))


PROVIDERS = {"anthropic": claude, "openai": openai, "gemini": gemini, "perplexity": perplexity,
             "openrouter": openrouter}


# ---------- Auswertung: Antwort als JSON ----------

def extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        return json.loads(text[a:b + 1])
    raise ValueError("Keine JSON-Antwort erhalten")


def analyse(provider, system, prompt):
    """Stellt eine Auswertungsfrage ohne Websuche und liefert das JSON-Ergebnis."""
    fn = PROVIDERS[provider]
    sys_ = system + "\n\nAntworte ausschließlich mit einem gültigen JSON-Objekt, ohne Erläuterung und ohne Codeblock."

    def call():
        text, _ = fn(prompt, system=sys_, web=False)
        return extract_json(text)

    return retry(call)
