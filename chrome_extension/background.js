// Peilung-Brücke: holt Suchaufträge von Peilung, führt sie in einem Hintergrund-Tab aus, meldet das Ergebnis.
// Adresse von Peilung; bei anderem Port hier anpassen und die Erweiterung neu laden.
const PEILUNG = "http://127.0.0.1:8000";

const HEADERS = {"X-Peilung-Bridge": "1"};

let running = false;

async function loop() {
  if (running) return;
  running = true;
  try {
    for (;;) {
      let job = null;
      try {
        const r = await fetch(PEILUNG + "/api/bridge/next", {headers: HEADERS});
        if (r.status === 200) job = await r.json();
        else if (r.status !== 204) { await sleep(10000); continue; }  // abgewiesen: nicht dauernd nachfragen
      } catch (e) {
        await sleep(10000);  // Peilung läuft gerade nicht
        continue;
      }
      if (job && job.id) await handle(job);
    }
  } finally {
    running = false;
  }
}

async function handle(job) {
  let tab = null, result;
  try {
    tab = await chrome.tabs.create({url: job.url, active: false});
    result = await readGoogle(tab.id);
  } catch (e) {
    result = {ok: false, error: String(e && e.message || e)};
  } finally {
    if (tab) chrome.tabs.remove(tab.id).catch(() => {});
  }
  await fetch(PEILUNG + "/api/bridge/result", {
    method: "POST", headers: {...HEADERS, "Content-Type": "application/json"},
    body: JSON.stringify({id: job.id, ...result}),
  }).catch(() => {});
}

// Wartet, bis die KI-Übersicht nicht mehr wächst, und klappt sie ggf. auf.
async function readGoogle(tabId) {
  let res = null, last = -1, stable = 0;
  for (let i = 0; i < 25; i++) {
    await sleep(1000);
    const t = await chrome.tabs.get(tabId);
    if ((t.url || "").includes("/sorry/")) return {ok: false, blocked: true, error: "Google hat die Suche gesperrt (Captcha)"};
    if (t.status !== "complete") continue;
    res = await run(tabId, extract);
    const size = res ? res.text.length : 0;
    stable = size === last ? stable + 1 : 0;
    last = size;
    if ((res && stable >= 2) || (!res && stable >= 6)) break;
  }
  if (res && await run(tabId, expand)) {
    await sleep(1500);
    res = (await run(tabId, extract)) || res;
  }
  return {ok: true, found: !!res, text: res ? res.text : "", links: res ? res.links : []};
}

async function run(tabId, func) {
  const [r] = await chrome.scripting.executeScript({target: {tabId}, func});
  return r ? r.result : null;
}

// Läuft in der Google-Seite: Überschrift der KI-Übersicht suchen, zum Block mit dem ganzen Text gehen.
function extract() {
  const leaf = [...document.querySelectorAll("*")].find(e => /^(Übersicht mit KI|AI Overview)$/.test(e.textContent.trim())
      && ![...e.children].some(c => /Übersicht mit KI|AI Overview/.test(c.textContent)));
  if (!leaf) return null;
  let box = leaf;
  while (box && box.innerText.length < 200) box = box.parentElement;
  if (!box) return null;
  return {text: box.innerText, links: [...box.querySelectorAll('a[href^="http"]')].map(a => a.href)};
}

function expand() {
  const b = [...document.querySelectorAll("[role=button],button")].find(x => /^(Mehr anzeigen|Show more)$/.test(x.innerText.trim()));
  if (b) b.click();
  return !!b;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Der Service Worker wird von Chrome schlafen gelegt; der Wecker startet die Schleife wieder.
chrome.alarms.create("peilung", {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(loop);
chrome.runtime.onStartup.addListener(loop);
chrome.runtime.onInstalled.addListener(loop);
loop();
