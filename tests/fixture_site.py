"""Kleine erfundene Firmen-Website für Tests und zum Ausprobieren ohne Internet.

Start: python tests/fixture_site.py  ->  http://localhost:8765
Die Seite hat absichtlich typische Schwächen (kurzer Titel, fehlende Beschreibungen, Bilder ohne Text).
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGES = {
    "/": ("Start", "", ["Willkommen bei Brückner", "Filter für die Industrie"],
          "Die Brückner Filtertechnik GmbH aus Kassel entwickelt und fertigt seit 1978 Filteranlagen für Industrie und Handwerk."),
    "/industriefilter/entstaubung": ("Entstaubungsanlagen | Brückner Filtertechnik", "Entstaubungsanlagen für Holz, Metall und Schüttgut.",
                                     ["Entstaubungsanlagen für die Holzverarbeitung"], "Patronenfilter und Schlauchfilter für Späne und Staub. " * 30),
    "/industriefilter/oelnebel": ("Ölnebelabscheider | Brückner Filtertechnik", "", ["Ölnebelabscheider für Werkzeugmaschinen"],
                                  "Abscheider für Kühlschmierstoff-Nebel an Dreh- und Fräsmaschinen. " * 30),
    "/industriefilter/schweissrauch": ("Schweißrauchabsaugung | Brückner Filtertechnik", "", ["Schweißrauchabsaugung für Fertigungshallen"],
                                       "Zentrale und mobile Absaugung nach geltenden Arbeitsschutzregeln. " * 30),
    "/reinraum/filterdecken": ("Filterdecken", "", ["Filterdecken für Reinräume"], "Laminar-Flow-Decken mit Schwebstofffiltern. " * 12),
    "/reinraum/schleusen": ("Schleusen", "", ["Material- und Personenschleusen"], "Schleusen für Reinräume der Klassen ISO 5 bis ISO 8. " * 12),
    "/service/wartung": ("Wartung | Brückner Filtertechnik", "", ["Wartung von Filteranlagen", "Notdienst"], "Wartungsverträge, Filterwechsel und Messungen. " * 25),
    "/service/ersatzfilter": ("Ersatzfilter", "", ["Ersatzfilter und Filterpatronen"], "Filterpatronen für Anlagen aller Hersteller."),
    "/unternehmen": ("Unternehmen | Brückner Filtertechnik", "Familienunternehmen aus Kassel.", ["Über Brückner Filtertechnik"],
                     "120 Beschäftigte, Fertigung in Kassel, Service in Deutschland, Österreich und der Schweiz. " * 10),
    "/kontakt": ("Kontakt", "", ["Kontakt"], "Brückner Filtertechnik GmbH, Kassel."),
}


def html(path):
    title, desc, h1s, text = PAGES[path]
    nav = "".join(f'<a href="{p}">{PAGES[p][2][0]}</a> ' for p in PAGES if p.count("/") <= 2)
    meta = f'<meta name="description" content="{desc}">' if desc else ""
    imgs = '<img src="/a.jpg"><img src="/b.jpg"><img src="/c.jpg" alt="Filteranlage">' if "industriefilter" in path else ""
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{title}</title>{meta}</head><body>'
            f'<header><nav>{nav}</nav></header><main>{"".join(f"<h1>{h}</h1>" for h in h1s)}<h2>Leistungen</h2>'
            f'<p>{text}</p>{imgs}</main><footer>© Brückner Filtertechnik GmbH</footer></body></html>')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base = f"http://localhost:{self.server.server_port}"
        if self.path == "/robots.txt":
            body, ctype = f"User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n\nSitemap: {base}/sitemap.xml\n", "text/plain"
        elif self.path == "/sitemap.xml":
            urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in PAGES)
            body, ctype = f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', "application/xml"
        elif self.path in PAGES:
            body, ctype = html(self.path), "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def serve(port=8765, background=False):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if background:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv
    print(f"Test-Website läuft auf http://localhost:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
