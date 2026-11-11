"""Website einlesen: Seiten finden, Inhalte für die Fragenableitung holen, Technik prüfen."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from . import config
from .textutil import same_site, domain_of

AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
           "PerplexityBot", "Google-Extended", "Bingbot"]


def client():
    return httpx.Client(headers={"User-Agent": config.USER_AGENT, "Accept-Language": "de,en;q=0.8"},
                        timeout=15, follow_redirects=True)


def fetch(c, url):
    try:
        r = c.get(url)
        return r.status_code, r.text, str(r.url), r.headers.get("content-type", "")
    except Exception as e:  # Netzwerkfehler dürfen die Prüfung nicht abbrechen
        return 0, "", url, f"error: {e.__class__.__name__}"


def _sitemap_urls(c, url, seen, limit):
    if url in seen or len(seen) > 20:
        return []
    seen.add(url)
    status, body, _, _ = fetch(c, url)
    if status != 200 or not body.strip():
        return []
    try:
        root = ElementTree.fromstring(body.encode("utf-8"))
    except ElementTree.ParseError:
        return []
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    if root.tag.endswith("sitemapindex"):
        out = []
        for loc in locs:
            out += _sitemap_urls(c, loc, seen, limit)
            if len(out) >= limit:
                break
        return out
    return locs


def parse_page(url, html):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")
    desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    robots = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    h2 = [h.get_text(" ", strip=True) for h in soup.find_all("h2")][:12]
    imgs = soup.find_all("img")
    ld_types = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack += d
            elif isinstance(d, dict):
                t = d.get("@type")
                ld_types += t if isinstance(t, list) else ([t] if t else [])
                stack += [v for v in d.values() if isinstance(v, (dict, list))]
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"]).split("#")[0]
        if href.startswith("http"):
            links.append((href, a.get_text(" ", strip=True)[:60]))
    nav_links = [urljoin(url, a["href"]).split("#")[0]
                 for n in soup.find_all(["nav", "header"]) for a in n.find_all("a", href=True)]
    hreflang = [l.get("hreflang") for l in soup.find_all("link", rel="alternate") if l.get("hreflang")]
    lang = (soup.html.get("lang") if soup.html else "") or ""
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return {
        "url": url, "title": title, "description": (desc.get("content", "").strip() if desc else ""),
        "noindex": bool(robots and "noindex" in robots.get("content", "").lower()),
        "h1": h1, "h2": h2, "words": len(text.split()), "text": text,
        "imgs": len(imgs), "imgs_no_alt": sum(1 for i in imgs if not (i.get("alt") or "").strip()),
        "ld_types": ld_types, "hreflang": hreflang, "lang": lang.lower()[:2],
        "links": links, "nav_links": nav_links,
    }


def crawl(site_url, max_pages=None):
    """Liest robots.txt, Sitemap, llms.txt und bis zu max_pages Seiten. Gibt ein dict zurück."""
    max_pages = max_pages or config.MAX_PAGES
    domain = domain_of(site_url)
    base = f"{urlparse(site_url).scheme or 'https'}://{urlparse(site_url).netloc or domain}"
    out = {"domain": domain, "base": base, "pages": [], "errors": []}
    with client() as c:
        status, html, final, ctype = fetch(c, site_url)
        out["home_status"], out["final_url"] = status, final
        if status != 200:
            out["errors"].append(f"Startseite nicht erreichbar (Status {status or ctype})")
            return out
        base = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
        out["base"], out["https"] = base, final.startswith("https://")
        home = parse_page(final, html)
        out["pages"].append(home)

        rs, robots_txt, _, _ = fetch(c, base + "/robots.txt")
        robots_txt = robots_txt if rs == 200 and "<html" not in robots_txt.lower()[:300] else ""
        out["robots"] = bool(robots_txt)
        out["blocked_bots"] = blocked_bots(robots_txt)
        ls, llms, _, lct = fetch(c, base + "/llms.txt")
        out["llms_txt"] = ls == 200 and bool(llms.strip()) and "<html" not in llms.lower()[:300]

        sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt) or [base + "/sitemap.xml"]
        urls, seen = [], set()
        for sm in sitemaps:
            urls += _sitemap_urls(c, sm, seen, max_pages * 3)
        urls = [u for u in dict.fromkeys(urls) if same_site(u, domain)]
        out["sitemap"] = bool(urls)
        out["sitemap_count"] = len(urls)
        if not urls:  # ohne Sitemap: interne Links der Startseite
            urls = [u for u, _ in home["links"] if same_site(u, domain)]
        skip = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|docx?|xlsx?)(\?|$)", re.I)
        nav = set(home["nav_links"])
        urls = [u for u in dict.fromkeys(urls) if u.rstrip("/") != final.rstrip("/") and not skip.search(u)]
        # Navigation zuerst, dann kurze Pfade: die wichtigsten Seiten kommen sicher in die Stichprobe
        urls.sort(key=lambda u: (u not in nav, urlparse(u).path.count("/"), len(u)))
        urls = urls[: max_pages - 1]

        def load(u):
            s, body, fin, ct = fetch(c, u)
            if s == 200 and "html" in ct.lower():
                p = parse_page(fin, body)
                p["in_nav"] = u in nav
                return p
            return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            out["pages"] += [p for p in pool.map(load, urls) if p]
    return out


def blocked_bots(robots_txt):
    """Welche KI-Crawler sind per robots.txt komplett ausgesperrt?"""
    blocked, agents, rules, last_agent = [], [], {}, False
    for line in robots_txt.splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        k, v = [s.strip() for s in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if not last_agent:
                agents = []
            agents.append(v.lower())
            last_agent = True
        elif k in ("disallow", "allow"):
            last_agent = False
            for a in agents:
                rules.setdefault(a, []).append((k, v))
    for bot in AI_BOTS:
        r = rules.get(bot.lower())
        if r is None:
            r = rules.get("*", [])
            specific = False
        else:
            specific = True
        if ("disallow", "/") in r and not any(k == "allow" and v in ("/", "") for k, v in r):
            blocked.append(bot if specific else f"{bot} (über *)")
    return blocked


def content_excerpt(data, max_pages=14, per_page=2500):
    """Text der wichtigsten Seiten für die Fragenableitung."""
    pages = data.get("pages", [])
    if not pages:
        return ""
    rest = sorted(pages[1:], key=lambda p: (not p.get("in_nav"), urlparse(p["url"]).path.count("/"), -p["words"]))
    parts = []
    for p in [pages[0]] + rest[: max_pages - 1]:
        head = " | ".join(p["h1"][:2] + p["h2"][:6])
        parts.append(f"### {p['url']}\nTitel: {p['title']}\nÜberschriften: {head}\n{p['text'][:per_page]}")
    return "\n\n".join(parts)


def audit(data):
    """Technische Prüfpunkte -> Liste von dicts (key, label, status, finding, metrics, examples)."""
    pages = data.get("pages", [])
    checks = []

    def add(key, label, status, finding, examples=None, **metrics):
        checks.append({"key": key, "label": label, "status": status, "finding": finding,
                       "examples": (examples or [])[:5], "metrics": metrics})

    if not pages:
        add("reach", "Erreichbarkeit", "fehlt", "; ".join(data.get("errors", [])) or "Website nicht erreichbar.")
        return checks
    n, home = len(pages), pages[0]
    ex = lambda cond: [p["url"] for p in pages if cond(p)]
    add("reach", "Erreichbarkeit und HTTPS", "gut" if data.get("https") else "teilweise",
        f"{n} Seiten geprüft; Startseite erreichbar" + ("" if data.get("https") else ", aber ohne HTTPS") + ".", pages=n)

    no_title = ex(lambda p: not p["title"])
    titles = [p["title"] for p in pages if p["title"]]
    dup = len(titles) - len(set(titles))
    weak_home = len(home["title"]) < 25
    st = "fehlt" if len(no_title) > n * .3 else ("teilweise" if no_title or dup > n * .1 or weak_home else "gut")
    f = f"{n - len(no_title)} von {n} Seiten mit Titel"
    if dup:
        f += f", {dup} Titel doppelt"
    f += f". Startseite: „{home['title'] or '–'}“"
    f += " – sehr kurz, ohne Hinweis auf das Angebot." if weak_home else "."
    add("title", "Seitentitel", st, f, no_title, missing=len(no_title), duplicates=dup,
        home_title=home["title"], weak_home=weak_home)

    no_desc = ex(lambda p: not p["description"])
    share = len(no_desc) / n
    add("description", "Beschreibungen für Suchtreffer", "gut" if share < .1 else ("teilweise" if share < .6 else "fehlt"),
        f"{len(no_desc)} von {n} Seiten ohne Beschreibung (meta description).", no_desc,
        missing=len(no_desc), home_missing=not home["description"])

    no_h1, multi_h1 = ex(lambda p: len(p["h1"]) == 0), ex(lambda p: len(p["h1"]) > 1)
    bad = len(no_h1) + len(multi_h1)
    add("h1", "Hauptüberschrift (H1)", "gut" if bad < n * .1 and len(home["h1"]) == 1 else ("teilweise" if len(no_h1) < n * .5 else "fehlt"),
        f"{len(no_h1)} Seiten ohne H1, {len(multi_h1)} mit mehreren. Startseite: {len(home['h1'])} H1"
        + (f" („{home['h1'][0][:70]}“)." if home["h1"] else "."), no_h1 + multi_h1,
        none=len(no_h1), multi=len(multi_h1), home_count=len(home["h1"]))

    thin = ex(lambda p: p["words"] < 200)
    med = sorted(p["words"] for p in pages)[n // 2]
    add("text", "Textmenge", "gut" if len(thin) < n * .2 else ("teilweise" if len(thin) < n * .6 else "fehlt"),
        f"Im Mittel {med} Wörter je Seite; {len(thin)} von {n} Seiten mit weniger als 200 Wörtern.", thin,
        thin=len(thin), median=med)

    types = {t for p in pages for t in p["ld_types"]}
    org = types & {"Organization", "LocalBusiness", "Corporation", "ProfessionalService", "Store"}
    add("structured", "Strukturierte Daten", "gut" if org else ("teilweise" if types else "fehlt"),
        ("Ausgezeichnet: " + ", ".join(sorted(types)[:8]) + "." if types else "Keine strukturierten Daten (JSON-LD) gefunden.")
        + ("" if org or not types else " Angaben zur Organisation fehlen."), has_org=bool(org), types=sorted(types)[:12])

    langs = {p["lang"] for p in pages if p["lang"]}
    hl = {h for p in pages for h in p["hreflang"]}
    no_lang = ex(lambda p: not p["lang"])
    add("lang", "Sprachangaben", "gut" if not no_lang else "teilweise",
        f"Sprachen laut Seiten: {', '.join(sorted(langs)) or 'keine Angabe'}"
        + (f"; hreflang für {', '.join(sorted(hl)[:6])}." if hl else "; keine hreflang-Verweise.")
        + (f" {len(no_lang)} Seiten ohne lang-Attribut." if no_lang else ""), no_lang, hreflang=bool(hl))

    rob, sm = data.get("robots"), data.get("sitemap")
    add("sitemap", "robots.txt und Sitemap", "gut" if rob and sm else ("teilweise" if rob or sm else "fehlt"),
        f"robots.txt {'vorhanden' if rob else 'fehlt'}; Sitemap {'mit ' + str(data.get('sitemap_count')) + ' Adressen' if sm else 'nicht gefunden'}.",
        robots=bool(rob), sitemap=bool(sm))

    bl = data.get("blocked_bots", [])
    add("aibots", "Zugang für KI-Crawler", "fehlt" if bl else "gut",
        ("Ausgesperrt per robots.txt: " + ", ".join(bl) + "." if bl else "Keine Sperren für KI-Crawler in der robots.txt."),
        blocked=bl)

    add("llms", "llms.txt", "gut" if data.get("llms_txt") else "fehlt",
        "Vorhanden." if data.get("llms_txt") else "Nicht vorhanden.")

    imgs, noalt = sum(p["imgs"] for p in pages), sum(p["imgs_no_alt"] for p in pages)
    r = noalt / imgs if imgs else 0
    add("alt", "Bildbeschreibungen", "gut" if r < .15 else ("teilweise" if r < .6 else "fehlt"),
        f"{noalt} von {imgs} Bildern ohne Alternativtext." if imgs else "Keine Bilder gefunden.",
        ex(lambda p: p["imgs"] and p["imgs_no_alt"] / p["imgs"] > .5), images=imgs, missing=noalt)

    noindex = ex(lambda p: p["noindex"])
    add("index", "Indexierbarkeit", "gut" if not noindex else ("teilweise" if not home["noindex"] else "fehlt"),
        f"{len(noindex)} von {n} geprüften Seiten sind auf noindex gesetzt." if noindex else "Keine geprüfte Seite ist von der Indexierung ausgeschlossen.",
        noindex, noindex=len(noindex))
    return checks
