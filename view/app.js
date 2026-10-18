/* bored - a terminal that thinks. Nothing on the page but the stream, typing itself out.
 * The stream grows forever, so the page tracks a global character index instead of
 * re-rendering. New characters queue and type out at a human rate, so you watch the
 * thought arrive rather than a paragraph appear. */
const term = document.getElementById("term");
let shown = -1;      // global index of the last character we were told about
let buf = "";        // on screen
let queue = "";      // accepted but not yet typed
const MAX = 9000;
const CPS = 55;

function paint() {
  if (buf.length > MAX) buf = "\u2026" + buf.slice(-MAX);
  term.textContent = buf;
  window.scrollTo(0, document.body.scrollHeight);
}

let acc = 0, last = performance.now();
function tick(now) {
  const dt = (now - last) / 1000; last = now;
  if (queue) {
    acc += dt * CPS;
    const n = Math.floor(acc);
    if (n > 0) { acc -= n; buf += queue.slice(0, n); queue = queue.slice(n); paint(); }
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

async function poll() {
  try {
    const r = await fetch("/snapshot.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const s = await r.json();
    const L = s.live;
    if (!L) return;
    const start = L.chars - L.text.length;
    if (shown < 0 || shown < start) { buf = L.text; queue = ""; shown = L.chars; paint(); }
    else if (L.chars > shown) { queue += L.text.slice(shown - start); shown = L.chars; }
    document.title = "bored - " + ((s.run || {}).ticks_total || L.breaths || 0);
  } catch (e) { /* blank on purpose */ }
}
poll();
setInterval(poll, 2500);
