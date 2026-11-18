"use strict";
const POS = { initial: "začiatok", medial: "stred", final: "koniec" };
const EXERCISE = { word: "slovo", syllable: "slabika", sound: "hláska" };
const VERDICT = { ok: "správne", partial: "čiastočne", wrong: "nesprávne", no_speech: "bez reči" };

async function loadChildren() {
  const kids = await api("/api/children");
  const sel = $("child");
  const prev = sel.value;
  sel.innerHTML = kids.length
    ? kids.map((k) => `<option value="${esc(k.code)}">${esc(k.code)} (${k.attempts} pokusov${k.consent_audio ? ", nahrávky" : ""})</option>`).join("")
    : `<option value="">— zatiaľ žiadne dieťa —</option>`;
  if (prev && kids.some((k) => k.code === prev)) sel.value = prev;
  await refresh();
}

async function refresh() {
  const code = $("child").value;
  $("export").href = code ? `/api/export.csv?child_code=${encodeURIComponent(code)}` : "/api/export.csv";
  if (!code) { $("stats").innerHTML = ""; $("attempts").innerHTML = ""; return; }

  const [stats, rows] = await Promise.all([
    api(`/api/stats/${encodeURIComponent(code)}`),
    api(`/api/attempts?child_code=${encodeURIComponent(code)}`),
  ]);

  $("stats").innerHTML = stats.map((s) => `
    <tr>
      <td><b>${esc(s.phoneme)}</b></td><td>${EXERCISE[s.exercise] || esc(s.exercise)}</td>
      <td class="num">${s.attempts}</td><td class="num">${s.words}</td>
      <td><span class="bar"><i style="width:${s.success_pct}%"></i></span> ${s.success_pct} %</td>
      <td class="num">${s.avg_score}</td><td class="num">${s.avg_stars}</td>
      <td class="num">${s.target_ok_pct ?? "—"} %</td><td class="num">${s.phone_ok_pct ?? "—"}${s.phone_ok_pct == null ? "" : " %"}</td>
      <td class="num">${s.overrides}</td>
      <td class="num">${s.avg_latency_ms} ms</td>
    </tr>`).join("") || `<tr><td colspan="11" class="muted">Žiadne pokusy.</td></tr>`;

  $("count").textContent = `(${rows.length})`;
  $("attempts").innerHTML = rows.map((r) => `
    <tr>
      <td class="muted">${esc(r.created_at)}</td>
      <td>${esc(r.phoneme)}</td><td class="muted">${EXERCISE[r.exercise || "word"]}</td><td><b>${esc(r.word)}</b></td>
      <td class="muted">${esc((r.positions || "").split(",").map((p) => POS[p] || p).join(", "))}</td>
      <td>„${esc(r.transcript)}“</td>
      <td class="ipa" title="${esc(r.phoneme_model || "")}">${r.recognized_phones == null ? '<span class="muted">—</span>'
        : `/${esc(r.recognized_phones)}/ <b>${esc(r.phone_detail || "")}</b>`}</td>
      <td class="num">${Math.round((r.similarity || 0) * 100)} %</td>
      <td class="num">${Math.round((r.confidence || 0) * 100)} %</td>
      <td class="num">${r.score}</td>
      <td>${"★".repeat(r.final_stars)}${"☆".repeat(3 - r.final_stars)}</td>
      <td><span class="tag ${r.verdict}">${VERDICT[r.verdict] || r.verdict}</span></td>
      <td>
        ${r.manual_override === null ? "" : r.manual_override ? "✓ uznal " : "✗ neuznal "}
        <button data-ov="1" data-id="${r.id}" title="Uznať">✓</button>
        <button data-ov="0" data-id="${r.id}" title="Neuznať">✗</button>
        ${r.manual_override === null ? "" : `<button data-ov="" data-id="${r.id}" title="Zrušiť zásah">↺</button>`}
      </td>
      <td><input class="said" data-label="${r.id}" value="${esc(r.actual_text)}" placeholder="${esc(r.word)}"></td>
      <td>${r.audio_path ? `<audio controls preload="none" src="/api/attempts/${r.id}/audio"></audio>` : '<span class="muted">—</span>'}</td>
    </tr>`).join("");
}

$("attempts").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-id]");
  if (!b) return;
  const correct = b.dataset.ov === "" ? null : b.dataset.ov === "1";
  await api(`/api/attempts/${b.dataset.id}/override`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ correct }),
  });
  refresh();
});

// anotácia "naozaj povedal" – uloží sa po opustení políčka alebo Enter
$("attempts").addEventListener("change", async (e) => {
  const inp = e.target.closest("input[data-label]");
  if (!inp) return;
  await api(`/api/attempts/${inp.dataset.label}/label`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actual_text: inp.value.trim() || null }),
  });
  inp.classList.add("saved");
});

$("child").addEventListener("change", refresh);
$("delete").addEventListener("click", async () => {
  const code = $("child").value;
  if (!code || !confirm(`Natrvalo vymazať všetky pokusy a nahrávky dieťaťa ${code}?`)) return;
  await api(`/api/children/${encodeURIComponent(code)}`, { method: "DELETE" });
  loadChildren();
});

loadChildren().catch((e) => alert(e.message));
