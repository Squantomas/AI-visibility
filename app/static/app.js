// Rückfragen vor folgenreichen Aktionen und Fortschrittsanzeige.
document.addEventListener('submit', function (e) {
  var msg = (e.submitter && e.submitter.dataset.confirm) || e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
  // Geänderter Wortlaut einer bereits gemessenen Frage: Hinweis auf den Neubeginn des Verlaufs.
  var t = e.target.querySelector('input[data-orig]');
  if (t && e.target.dataset.measured === '1' && t.value.trim() !== t.dataset.orig &&
      !(e.submitter && e.submitter.dataset.confirm)) {
    if (!window.confirm('Der Wortlaut wurde geändert. Der Verlauf dieser Frage beginnt damit neu und wird im nächsten Bericht als Neubeginn gekennzeichnet. Fortfahren?')) e.preventDefault();
  }
});
function poll(url, done) {
  fetch(url).then(function (r) { return r.json(); }).then(function (d) {
    if (!done(d)) setTimeout(function () { poll(url, done); }, 2000);
  }).catch(function () { setTimeout(function () { poll(url, done); }, 4000); });
}
