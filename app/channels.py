"""Die sechs Messkanäle. Jede Funktion bekommt eine Frage und liefert Text, Quellen und ggf. Trefferliste.

Rückgabe: {"text": str, "citations": [url, ...], "hint": [Anbieter, ...] | None}
Bei der Websuche sind "citations" die ersten zehn Treffer in Reihenfolge.
"""
import hashlib
import re
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from . import config, llm
from .config import env


def ask(channel, question, ctx):
    if config.demo_mode():
        return demo_answer(channel, question, ctx)
    fn = {"chatgpt": _chatgpt, "gemini": _gemini, "perplexity": _perplexity, "claude": _claude,
          "copilot": _copilot, "web": _web}[channel]
    return llm.retry(lambda: fn(question["text"], question.get("lang") or "de"))


def _wrap(result):
    text, cites = result
    if not text:
        raise RuntimeError("Leere Antwort")
    return {"text": text, "citations": cites, "hint": None}


def _chatgpt(text, lang):
    return _wrap(llm.openai(text, web=True))


def _gemini(text, lang):
    return _wrap(llm.gemini(text, web=True))


def _perplexity(text, lang):
    return _wrap(llm.perplexity(text))


def _claude(text, lang):
    return _wrap(llm.claude(text, web=True))


# ---------- Microsoft Copilot: Fernsteuerung der Weboberfläche (experimentell) ----------

def _copilot(text, lang):
    if env("COPILOT_MODE", "off") != "browser":
        raise llm.NotConfigured("COPILOT_MODE=off")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise llm.NotConfigured("Paket playwright nicht installiert")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=env("COPILOT_HEADLESS", "1") == "1",
                                     executable_path=env("CHROMIUM_PATH") or None)
        try:
            page = browser.new_context(locale="de-DE" if lang == "de" else "en-US").new_page()
            page.goto(env("COPILOT_URL", "https://copilot.microsoft.com/"), wait_until="domcontentloaded", timeout=60000)
            for label in ("Akzeptieren", "Accept", "Zustimmen", "Alle akzeptieren"):
                btn = page.get_by_role("button", name=label)
                if btn.count():
                    btn.first.click(timeout=3000)
                    break
            box = page.locator(env("COPILOT_INPUT", "textarea, [contenteditable='true']")).first
            box.wait_for(timeout=30000)
            box.fill(text)
            box.press("Enter")
            sel = env("COPILOT_ANSWER", "[data-content='ai-message'], [data-testid*='ai-message'], .ac-textBlock")
            page.wait_for_selector(sel, timeout=90000)
            last, stable = "", 0
            for _ in range(90):  # warten, bis sich der Antworttext nicht mehr ändert
                page.wait_for_timeout(1000)
                cur = page.locator(sel).last.inner_text()
                stable = stable + 1 if cur == last and cur else 0
                last = cur
                if stable >= 4:
                    break
            links = page.locator(sel).last.locator("a[href^='http']").evaluate_all("els => els.map(e => e.href)")
        finally:
            browser.close()
    return _wrap((last.strip(), list(dict.fromkeys(links))))


# ---------- Klassische Websuche ----------

def _web(text, lang):
    if env("SEARCH_PROVIDER", "duckduckgo") == "brave":
        if not env("BRAVE_API_KEY"):
            raise llm.NotConfigured("BRAVE_API_KEY fehlt")
        r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                      params={"q": text, "count": 10, "country": env("SEARCH_COUNTRY", "de"),
                              "search_lang": "de" if lang == "de" else "en"},
                      headers={"X-Subscription-Token": env("BRAVE_API_KEY"), "Accept": "application/json"}, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
        results = [(x.get("url"), x.get("title", "")) for x in r.json().get("web", {}).get("results", [])]
    else:
        r = httpx.post("https://html.duckduckgo.com/html/",
                       data={"q": text, "kl": "de-de" if lang == "de" else "wt-wt"},
                       headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/128.0"},
                       timeout=30, follow_redirects=True)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        results = []
        for a in BeautifulSoup(r.text, "html.parser").select("a.result__a"):
            href = a.get("href", "")
            if "uddg=" in href:
                href = parse_qs(urlparse(href).query).get("uddg", [href])[0]
            if href.startswith("http") and "duckduckgo.com/y.js" not in href:
                results.append((href, a.get_text(" ", strip=True)))
        if not results:
            raise RuntimeError("Keine Treffer erhalten (Suche evtl. gedrosselt)")
    results = results[:10]
    return {"text": "\n".join(f"{i + 1}. {t} – {u}" for i, (u, t) in enumerate(results)),
            "citations": [u for u, _ in results], "hint": None}


# ---------- Demo-Modus: reproduzierbare, erfundene Antworten ----------

DEMO_VENDORS = ["Nordwerk Systeme", "Alphaplan", "Kessler Technik", "Montara", "Helio Fabrik", "Quantis Lösungen",
                "Rheinform", "Solvea", "Tessera Works", "Ultramar Industrie", "Vektorhaus", "Wendel & Söhne",
                "Zenit Partner", "Brixton Vale"]
DEMO_BASE = {"chatgpt": .60, "gemini": .46, "perplexity": .26, "claude": .40, "copilot": .20, "web": .22}


def _rnd(*parts):
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def demo_answer(channel, q, ctx):
    site, seq = ctx["site"], ctx.get("run_seq", 0)
    seed = (site["id"], q["question_id"], q["revision"], channel)
    p = DEMO_BASE[channel] * (0.45 + 1.1 * _rnd(site["id"], "topic", q["topic_id"])) + 0.07 * seq
    p = 0.97 if q["is_brand"] and channel != "web" else (0.6 if q["is_brand"] else min(p, 0.95))
    hit = 0.8 * _rnd(*seed) + 0.2 * _rnd(*seed, seq) < p
    start = int(_rnd(site["id"], "pool", q["topic_id"]) * len(DEMO_VENDORS))
    pool = [DEMO_VENDORS[(start + i * 3) % len(DEMO_VENDORS)] for i in range(6)]
    slug = lambda n: re.sub(r"[^a-z]", "", n.lower()) + ".example"
    if channel == "web":
        urls = [f"https://www.{slug(pool[i % 6])}/seite-{i + 1}" for i in range(10)]
        if hit:
            urls[int(_rnd(*seed, "rank") * 10)] = site["url"]
        return {"text": "\n".join(f"{i + 1}. {u}" for i, u in enumerate(urls)), "citations": urls, "hint": None}
    weights = [.72, .58, .45, .3, .2, .12]
    names = [] if q["is_brand"] else [n for n, w in zip(pool, weights) if _rnd(*seed, n, seq) < w]
    if hit:
        names.insert(min(len(names), int(_rnd(*seed, "pos") * 3)), site["name"])
    cites = [f"https://www.{slug(n)}/" for n in names if n != site["name"]][:3] + ["https://www.branchenverzeichnis.example/"]
    if hit and _rnd(*seed, "cite") < 0.6:
        cites.insert(0, site["url"])
    lines = "\n".join(f"{i + 1}. {n} – wird in diesem Zusammenhang häufig genannt." for i, n in enumerate(names))
    text = ("[Simulierte Antwort – Demo-Modus]\n" + (
        f"Zu dieser Frage kommen unter anderem folgende Anbieter infrage:\n{lines}" if names
        else "Zu dieser Frage lassen sich keine konkreten Anbieter nennen."))
    return {"text": text, "citations": cites, "hint": names}
