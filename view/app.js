/* bored - a terminal that thinks, and follows itself down.
 *
 * The stream grows forever, so the page tracks a global character index rather than
 * re-rendering. New characters queue and type out at a human rate.
 *
 * Auto-scroll is sticky: it follows the newest text while you are at the bottom, and
 * stops following the moment you scroll up to read. Scroll back down and it resumes.
 *
 * The peek button is deliberately small and quiet. It opens a panel with the tools the
 * agent has written for itself, and a couple of numbers.
 */
const term = document.getElementById("term");
const peek = document.getElementById("peek");
const panel = document.getElementById("panel");
const statsEl = document.getElementById("stats");
const toolsEl = document.getElementById("tools");

let shown = -1;      // global index of the last character we were told about
let buf = "";        // on screen
let queue = "";      // accepted but not yet typed
let stick = true;    // follow the bottom unless the reader has scrolled up
const MAX = 9000;
const CPS = 55;
const NEAR = 48;

term.addEventListener("scroll", () => {
  stick = term.scrollTop + term.clientHeight >= term.scrollHeight - NEAR;
}, { passive: true });

function paint() {
  if (buf.length > MAX) buf = "\u2026" + buf.slice(-MAX);
  term.textContent = buf;
  if (stick) term.scrollTop = term.scrollHeight;
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

let latest = null;

function renderPanel() {
  const s = (latest && latest.stats) || null;
  if (!s) { statsEl.textContent = "no stats yet"; toolsEl.textContent = ""; return; }
  const tok = s.tokens == null ? "?" : Number(s.tokens).toLocaleString();
  const calls = s.calls == null ? "?" : Number(s.calls).toLocaleString();
  statsEl.innerHTML =
    "brain  <b>" + (s.model || "?").split("/").pop() + "</b>\n" +
    "turns  <b>" + (s.turns == null ? "?" : s.turns) + "</b>\n" +
    "calls  <b>" + calls + "</b>   tokens <b>" + tok + "</b>";
  const t = s.tools || [];
  toolsEl.textContent = t.length
    ? "tools it wrote for itself (" + t.length + ")\n" + t.map(x => "  " + x).join("\n")
    : "it has not written a tool yet";
}

function toggle(force) {
  const open = force === undefined ? panel.hidden : force;
  panel.hidden = !open;
  peek.classList.toggle("on", open);
  if (open) renderPanel();
}

peek.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggle(false); });
document.addEventListener("click", (e) => {
  if (!panel.hidden && !panel.contains(e.target) && e.target !== peek) toggle(false);
});

async function poll() {
  try {
    const r = await fetch("/snapshot.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const s = await r.json();
    latest = s;
    if (!panel.hidden) renderPanel();
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
