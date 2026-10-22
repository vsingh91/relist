// Shared helpers for the two Relist screens.

const CHECKS = {
  colour: "Colour",
  shape: "Shape",
  pattern: "Pattern",
  logo_text: "Logo / text",
  missing_parts: "Parts",
  wear_visible: "Wear kept",
  photo_quality: "Photo quality",
};

async function loadRuns() {
  const res = await fetch("/api/runs");
  return res.json();
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function img(run, file, cls = "") {
  if (!file) return el("div", { class: `noimg ${cls}` }, "no image");
  const src = `/runs/${run.id}/${file.startsWith("originals/") ? file : "edits/" + file}`;
  return el("img", { src, class: `zoomable ${cls}`, loading: "lazy", onclick: () => zoom(src) });
}

function zoom(src) {
  let box = document.getElementById("lightbox");
  if (!box) {
    box = el("div", { id: "lightbox", onclick: () => box.classList.remove("on") }, el("img"));
    document.body.append(box);
  }
  box.querySelector("img").src = src;
  box.classList.add("on");
}

function money(x, digits = 2) {
  return x === null || x === undefined ? "–" : `$${Number(x).toFixed(digits)}`;
}

function pct(x) {
  return x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`;
}

function nice(name) {
  return name.replace(/[-_]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function modeLabel(mode) {
  return { agent: "Agent", fixed: "Fixed rules", looks: "Look test" }[mode] || mode;
}

function runLabel(run) {
  return `${modeLabel(run.mode)} · ${run.started} · ${run.items.length} items`;
}

function publishedAttempt(item) {
  return (item.attempts || []).find((a) => a.n === item.published_attempt) || null;
}

// Your grade for one attempt: overall pass if no check marked fail.
function gradeOverall(grade) {
  if (!grade || !grade.checks) return null;
  const vals = Object.values(grade.checks);
  if (!vals.length) return null;
  return vals.includes("fail") ? "fail" : "pass";
}

function runSelect(runs, current, onChange, filter = () => true) {
  const sel = el("select", { onchange: (e) => onChange(e.target.value) });
  for (const r of runs.filter(filter)) {
    sel.append(el("option", { value: r.id, selected: r.id === current ? "selected" : null }, runLabel(r)));
  }
  return sel;
}
