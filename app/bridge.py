"""Brücke zur Peilung-Erweiterung in Ihrem Chrome: Suchaufträge abgeben, Ergebnisse abholen.

Die Erweiterung fragt per Long-Polling nach Aufträgen (/api/bridge/next), öffnet die Seite in einem
Hintergrund-Tab Ihres normalen Chrome, liest sie aus und meldet das Ergebnis (/api/bridge/result).
"""
import itertools
import threading
import time

_cond = threading.Condition()
_queue = []          # wartende Aufträge
_results = {}        # id -> Ergebnis
_ids = itertools.count(1)
_last_seen = [0.0]   # letzter Kontakt der Erweiterung


def connected(within=75):
    return time.time() - _last_seen[0] < within


def submit(kind, url, timeout=120):
    """Auftrag abgeben und auf das Ergebnis warten. -> dict der Erweiterung oder TimeoutError."""
    with _cond:
        job = {"id": next(_ids), "kind": kind, "url": url}
        _queue.append(job)
        _cond.notify_all()
        end = time.time() + timeout
        while job["id"] not in _results:
            left = end - time.time()
            if left <= 0:
                if job in _queue:
                    _queue.remove(job)
                raise TimeoutError("Die Chrome-Erweiterung hat nicht rechtzeitig geantwortet")
            _cond.wait(left)
        return _results.pop(job["id"])


def next_job(wait=20):
    """Für die Erweiterung: nächsten Auftrag holen, höchstens `wait` Sekunden warten."""
    _last_seen[0] = time.time()
    with _cond:
        end = time.time() + wait
        while not _queue:
            left = end - time.time()
            if left <= 0:
                return None
            _cond.wait(left)
        return _queue.pop(0)


def deliver(job_id, result):
    _last_seen[0] = time.time()
    with _cond:
        _results[job_id] = result
        _cond.notify_all()
