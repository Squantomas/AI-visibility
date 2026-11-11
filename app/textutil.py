"""Kleine Text-Helfer: Schreibweisen vereinheitlichen, Marke erkennen, Domains vergleichen."""
import re
import unicodedata
from urllib.parse import urlparse

_UML = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
_UML_SIMPLE = {"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}
LEGAL = (r"\b(gmbh\s*&\s*co\.?\s*kg|gmbh|ag|se|kg|ohg|ug|e\.?\s?k\.?|mbh|inc\.?|llc|ltd\.?|corp\.?|"
         r"corporation|co\.|s\.?a\.?|b\.?v\.?|s\.?r\.?l\.?|plc|kft\.?|group|gruppe|holding)\b")


def fold(text, simple=False):
    """Kleinschreibung, Umlaute auflösen (ö->oe, mit simple=True ö->o), Akzente entfernen."""
    t = (text or "").lower()
    for k, v in (_UML_SIMPLE if simple else _UML).items():
        t = t.replace(k, v)
    t = unicodedata.normalize("NFKD", t)
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def vendor_key(name):
    """Vergleichsschlüssel für Anbieternamen: ohne Rechtsform, Satzzeichen, Leerzeichen."""
    t = fold(name)
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(LEGAL, " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def domain_of(url):
    if not url:
        return ""
    if "//" not in url:
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(url_or_domain, domain):
    d = domain_of(url_or_domain)
    return bool(d) and bool(domain) and (d == domain or d.endswith("." + domain))


def default_aliases(name, domain):
    """Schreibweisen der Marke: Name, Name ohne Rechtsform, Domain-Kern."""
    out = []
    for cand in [name, re.sub(LEGAL, "", name or "", flags=re.I).strip(" -–,.")]:
        if cand and cand not in out:
            out.append(cand)
    core = (domain or "").split(".")[0]
    if len(core) >= 3 and core not in [fold(a) for a in out]:
        out.append(core)
    return out


def alias_patterns(aliases, domain=""):
    pats = set()
    for a in list(aliases or []) + ([domain] if domain else []):
        for simple in (False, True):
            f = fold(a, simple).strip()
            if len(f) >= 3:
                pats.add(f)
    return [re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])") for p in sorted(pats)]


def mentions(text, patterns):
    """Wird die Marke im Text genannt? Geprüft in beiden Umlaut-Schreibweisen."""
    if not text:
        return False
    a, b = fold(text), fold(text, simple=True)
    return any(p.search(a) or p.search(b) for p in patterns)


def is_alias(name, aliases, domain=""):
    k = vendor_key(name)
    if not k:
        return False
    keys = {vendor_key(a) for a in aliases or []} | {vendor_key(fold(a, True)) for a in aliases or []}
    core = (domain or "").split(".")[0]
    if core:
        keys.add(vendor_key(core))
    keys.discard("")
    return k in keys or vendor_key(fold(name, True)) in keys


def words(text):
    return set(w for w in re.findall(r"[a-z0-9]{4,}", fold(text)))
