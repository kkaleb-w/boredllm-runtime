/* bored — live view. Polls snapshot.json. Never sends anything back. */
const $ = (id) => document.getElementById(id);
let lastN = 0;

const pct = (v) => (v === null || v === undefined) ? "—" : v + "%";

function draw(series) {
  const c = $("chart"), dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = 150;
  c.width = w * dpr; c.height = h * dpr;
  const x = c.getContext("2d");
  x.scale(dpr, dpr);
  x.clearRect(0, 0, w, h);
  if (!series || series.length < 2) {
    x.fillStyle = "#6d6a66"; x.font = "11px ui-monospace"; x.fillText("not enough ticks yet", 4, 20);
    return;
  }
  const pad = 6, n = series.length;
  const px = (i) => pad + (w - pad * 2) * (i / (n - 1));
  const py = (v) => h - pad - (h - pad * 2) * Math.max(0, Math.min(1, v));
  const styles = getComputedStyle(document.body);
  const line = (key, color, scale) => {
    x.beginPath(); x.strokeStyle = color; x.lineWidth = 1.25;
    series.forEach((d, i) => {
      const v = (d[key] ?? 0) / (scale || 1);
      i ? x.lineTo(px(i), py(v)) : x.moveTo(px(i), py(v));
    });
    x.stroke();
  };
  x.strokeStyle = "#1d1f22"; x.lineWidth = 1;
  [0.25, 0.5, 0.75].forEach((f) => { x.beginPath(); x.moveTo(pad, py(f)); x.lineTo(w - pad, py(f)); x.stroke(); });
  line("rep", styles.getPropertyValue("--rep").trim(), 1);          // 0..1
  line("inv", styles.getPropertyValue("--inv").trim(), 100);        // percent
  line("inhabit", styles.getPropertyValue("--inh").trim(), 100);
}

function render(snap) {
  const h = snap.headline || {}, r = snap.run || {};
  $("rep").textContent = h.repetition ?? "—";
  $("invent").textContent = pct(h.invention_pct);
  $("inhabit").textContent = pct(h.inhabit_pct);
  $("ticks").textContent = r.ticks_total ?? "—";
  $("sub").textContent = `${r.creatures?.length || 0} creature(s), ${r.model || "?"}`;
  draw(snap.series);

  const ol = $("stream");
  ol.innerHTML = "";
  (snap.stream || []).forEach((t) => {
    const li = document.createElement("li");
    if (t.n_invented_refs) li.className = "c";
    const meta = document.createElement("div");
    meta.className = "meta";
    const tag = t.stance || "?";
    meta.innerHTML = `<b>${t.creature || ""}</b> ${String(t.ts || "").slice(11, 16)} ` +
      `stim ${(t.stimulation ?? 0).toFixed(2)} <span class="tag ${tag}">${tag}</span>` +
      (t.n_invented_refs ? ` <span class="tag">invents ${t.n_invented_refs}</span>` : "");
    const body = document.createElement("div");
    body.className = "t";
    body.textContent = t.thought || "(nothing)";
    li.append(meta, body);
    ol.append(li);
  });

  const hn = snap.health || {};
  $("foot").textContent = `${snap.generated_at} · last tick ${hn.last_tick_age_s ?? "?"}s ago · ` +
    `records ${hn.records ?? 0} · ${h.drift_note || ""}`;
}

async function poll() {
  try {
    const r = await fetch("/snapshot.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const s = await r.json();
    render(s);
    const n = (s.run || {}).ticks_total || 0;
    document.title = "bored — " + n + " ticks";
    if (n !== lastN) { lastN = n; }
  } catch (e) {
    $("foot").textContent = "no snapshot yet (" + e.message + ")";
  }
}
poll();
setInterval(poll, 20000);
addEventListener("resize", () => { if (window.__s) draw(window.__s.series); });
