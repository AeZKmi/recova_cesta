/* Spoločné pomocné funkcie hry a panela pre logopéda */
"use strict";
const $ = (id) => document.getElementById(id);

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* opts.timeout (sekundy): po uplynutí sa požiadavka zruší, aby hra nezostala visieť */
async function api(url, { timeout, ...opts } = {}) {
  let r, timer;
  if (timeout) {
    const ctl = new AbortController();
    opts.signal = ctl.signal;
    timer = setTimeout(() => ctl.abort(), timeout * 1000);
  }
  try {
    r = await fetch(url, opts);
  } catch (err) {
    throw new Error(err.name === "AbortError" ? "server neodpovedá, skús to znova" : "server nie je dostupný");
  } finally {
    clearTimeout(timer);
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

/* ---------------------------------------------------------- téma ---
 * Svetlá (predvolená) / tmavá. Voľba sa pamätá v prehliadači; bez voľby
 * sa použije svetlá téma. Atribút data-theme nastavuje aj krátky skript
 * v <head>, aby stránka nepreblikla. */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = $("theme-toggle");
  if (btn) {
    btn.textContent = theme === "dark" ? "☀️ Svetlá téma" : "🌙 Tmavá téma";
  }
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("theme", next); } catch {}
  applyTheme(next);
}

document.addEventListener("DOMContentLoaded", () => {
  let saved = "light";
  try { saved = localStorage.getItem("theme") || "light"; } catch {}
  applyTheme(saved);
  const btn = $("theme-toggle");
  if (btn) btn.onclick = toggleTheme;
});
