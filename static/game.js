/* Rečová cesta – logika hry (bez frameworkov) */
"use strict";

const REWARDS = {
  common: ["🍪", "🎈", "🧸", "🪁", "🌼", "🐚", "🍭", "⚽"],
  rare: ["🦄", "🌈", "🚀", "🏆", "🎸", "🐬"],
  legendary: ["🐉", "👑", "💎", "🌟"],
};

const PRAISE = ["Super!", "Výborne!", "Si šikovný!", "Bravó!", "Paráda!"];
const ENCOURAGE = ["Skúsime to ešte raz?", "Nevadí, ide ti to!", "Skoro! Ešte raz.", "Si statočný, skús znova."];

const state = {
  cfg: null, words: null,
  child: "", phoneme: "R", level: 1, exercise: "word",
  count: 6,             // počet úloh v jednom hraní
  rewardAt: 12,         // políčko s pokladom (počet hviezdičiek na jeho získanie)
  rewardFound: false,
  list: [], index: 0, attempt: 0,
  position: 0, keys: 0, starsTotal: 0,
  last: null,           // posledný výsledok zo servera
  prevBest: 0,          // najlepšie hviezdičky z predošlých pokusov o tú istú úlohu
  session: "",
  busy: false,
  ownUrl: null,         // posledná nahrávka dieťaťa (len v prehliadači, na prehranie)
};

const recorder = new VoiceRecorder({
  onLevel: (v) => ($("meter-fill").style.width = `${Math.round(v * 100)}%`),
});

/* ---------------------------------------------------------- pomocné --- */
function show(screen) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(`screen-${screen}`).classList.add("active");
  // počas hry sa hlavička a päta skryjú, aby sa hra zmestila na obrazovku
  document.body.classList.toggle("playing", screen === "game");
  if (screen !== "game") recorder.close();     // mimo hry mikrofón nepočúva
  window.scrollTo(0, 0);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
function say(text, mood = "") {
  $("bubble").textContent = text;
  const r = $("robot");
  r.className = `robot ${mood}`;
  void r.offsetWidth;            // reštart CSS animácie
  r.classList.add("bump");
}

/* jednoduché zvuky cez Web Audio (žiadne cudzie súbory) */
let audioCtx;
function chime(stars) {
  try {
    audioCtx = audioCtx || new AudioContext();
    const notes = stars >= 1 ? [523, 659, 784, 1047].slice(0, stars + 1) : [330, 262];
    notes.forEach((f, i) => {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = "triangle"; o.frequency.value = f;
      const t = audioCtx.currentTime + i * 0.13;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
      o.connect(g).connect(audioCtx.destination);
      o.start(t); o.stop(t + 0.32);
    });
  } catch { /* zvuk nie je nevyhnutný */ }
}

function blip(freq = 660) {
  try {
    audioCtx = audioCtx || new AudioContext();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.type = "sine"; o.frequency.value = freq;
    const t = audioCtx.currentTime;
    g.gain.setValueAtTime(0.12, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
    o.connect(g).connect(audioCtx.destination);
    o.start(t); o.stop(t + 0.13);
  } catch {}
}

/* konfety – len CSS animácia, pri „obmedzenom pohybe“ sa nespustia */
function confetti(count = 40) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const box = $("confetti");
  const colors = ["#f28c28", "#ffb84d", "#f5b400", "#e5484d", "#2f9e5b", "#ff7a59"];
  for (let i = 0; i < count; i++) {
    const c = document.createElement("i");
    const star = Math.random() < 0.2;
    c.textContent = star ? "⭐" : "";
    c.className = star ? "star" : "";
    c.style.cssText = `left:${Math.random() * 100}%; background:${star ? "none" : pick(colors)};
      --dx:${Math.round(Math.random() * 240 - 120)}px; --rot:${Math.round(Math.random() * 720 - 360)}deg;
      animation-duration:${(1.6 + Math.random() * 1.4).toFixed(2)}s; animation-delay:${(Math.random() * 0.3).toFixed(2)}s`;
    c.onanimationend = () => c.remove();
    box.appendChild(c);
  }
}

/* ---------------------------------------------------------- nálepky ---
 * Zbierka odmien medzi hrami. Ukladá sa len v prehliadači, podľa kódu dieťaťa. */
function loadStickers(code) {
  try { return JSON.parse(localStorage.getItem("stickers") || "{}")[code] || []; } catch { return []; }
}
function addSticker(code, icon, tier) {
  try {
    const all = JSON.parse(localStorage.getItem("stickers") || "{}");
    (all[code] = all[code] || []).push({ icon, tier });
    localStorage.setItem("stickers", JSON.stringify(all));
  } catch {}
}
function renderAlbum(box, list, code, markLast = false) {
  const stickers = loadStickers(code);
  $(box).classList.toggle("hidden", !stickers.length);
  $(list).innerHTML = stickers.map((s, i) =>
    `<span class="sticker ${esc(s.tier)}${markLast && i === stickers.length - 1 ? " new" : ""}">${esc(s.icon)}</span>`).join("");
  return stickers.length;
}

/* ---------------------------------------------------------- prehrávanie ---
 * Vlastná nahrávka sa prehráva priamo z prehliadača (blob), takže funguje
 * aj bez súhlasu s ukladaním – na server sa kvôli tomu nič neukladá. */
const player = new Audio();

function stopPlayback() {
  player.pause();
  $("btn-play-own").classList.remove("playing");
}

function playOwn() {
  if (!state.ownUrl) return;
  const btn = $("btn-play-own");
  stopPlayback();
  player.onended = player.onerror = () => btn.classList.remove("playing");
  player.src = state.ownUrl;
  btn.classList.add("playing");
  player.play().catch(() => btn.classList.remove("playing"));
}

function setOwnRecording(blob) {
  if (state.ownUrl) URL.revokeObjectURL(state.ownUrl);
  state.ownUrl = blob ? URL.createObjectURL(blob) : null;
}

function showCompare(on) {
  $("compare").classList.toggle("hidden", !on || !state.ownUrl);
}

/* ---------------------------------------------------------- nastavenie --- */
async function initSetup() {
  [state.cfg, state.words] = await Promise.all([api("/api/config"), api("/api/words")]);
  const models = [state.cfg.model, state.cfg.phoneme_model].filter(Boolean).join(" + ");
  $("model-name").textContent = `${models} (lokálne)`;
  recorder.maxSeconds = state.cfg.max_record_seconds;

  const box = $("phoneme-buttons");
  box.innerHTML = "";
  Object.entries(state.words).forEach(([key, p], i) => {
    const b = document.createElement("button");
    b.className = "chip big-chip" + (i === 0 ? " on" : "");
    b.textContent = p.label;
    b.dataset.phoneme = key;
    box.appendChild(b);
  });
  state.phoneme = Object.keys(state.words)[0];

  box.onclick = (e) => {
    const b = e.target.closest("[data-phoneme]");
    if (!b) return;
    box.querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
    b.classList.add("on");
    state.phoneme = b.dataset.phoneme;
  };
  $("exercise-buttons").onclick = (e) => {
    const b = e.target.closest("[data-exercise]");
    if (!b) return;
    $("exercise-buttons").querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
    b.classList.add("on");
    state.exercise = b.dataset.exercise;
    updateExerciseNote();
  };
  updateExerciseNote();
  $("level-buttons").onclick = (e) => {
    const b = e.target.closest("[data-level]");
    if (!b) return;
    $("level-buttons").querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
    b.classList.add("on");
    state.level = Number(b.dataset.level);
  };

  $("count-buttons").onclick = (e) => {
    const b = e.target.closest("[data-count]");
    if (!b) return;
    $("count-buttons").querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
    b.classList.add("on");
    state.count = Number(b.dataset.count);
    updateRewardRange(true);
  };
  $("reward-range").oninput = () => updateRewardRange(false);
  $("child-code").oninput = () =>
    renderAlbum("album-setup", "album-setup-list", $("child-code").value.trim());
  $("adult-panel").ontoggle = () => {
    try { localStorage.setItem("adultOpen", $("adult-panel").open ? "1" : ""); } catch {}
  };

  try {
    $("child-code").value = localStorage.getItem("childCode") || "";
    $("mic-processing").checked = localStorage.getItem("micProcessing") === "1";
    $("adult-panel").open = localStorage.getItem("adultOpen") === "1";
    const count = Number(localStorage.getItem("count"));
    const chip = $("count-buttons").querySelector(`[data-count="${count}"]`);
    if (chip) { chip.click(); }
    const at = Number(localStorage.getItem("rewardAt"));
    if (at) { $("reward-range").value = at; updateRewardRange(false); }
  } catch {}
  updateRewardRange(false);
  $("child-code").oninput();
}

/* posuvník „poklad na políčku“: rozsah závisí od počtu úloh (3 ★ za úlohu) */
function updateRewardRange(resetValue) {
  const range = $("reward-range");
  const max = state.count * 3;
  range.max = max;
  range.min = Math.min(3, max);
  if (resetValue || Number(range.value) > max) range.value = Math.round(max * 2 / 3);
  state.rewardAt = Number(range.value);
  $("reward-label").textContent = `${state.rewardAt} z ${max} ★`;
}

function updateExerciseNote() {
  $("level-field").classList.toggle("hidden", state.exercise !== "word");
  const noPhoneme = !state.cfg.phoneme_model;
  $("exercise-note").textContent = state.exercise !== "word" && noPhoneme
    ? "⚠ Fonémový model nie je načítaný – hlásky a slabiky sa hodnotia len podľa prepisu (nespoľahlivé)."
    : state.exercise === "word" && !noPhoneme
      ? "Slovo hodnotí model pre slová, cieľovú hlásku fonémový model."
      : "";
}

/* zoznam úloh podľa cvičenia */
function buildList() {
  const p = state.words[state.phoneme];
  if (state.exercise === "sound") {
    return Array.from({ length: state.count }, () => p.sound);
  }
  const pool = state.exercise === "syllable" ? p.syllables || [] : p.levels[String(state.level)] || [];
  return shuffle(pool).slice(0, state.count);
}

const TASK_NAME = { sound: "Hláska", syllable: "Slabika", word: "Slovo" };

async function startGame() {
  const code = $("child-code").value.trim();
  $("setup-error").textContent = "";
  if (!/^[A-Za-z0-9_-]{1,20}$/.test(code)) {
    $("setup-error").textContent = "Zadajte kód dieťaťa (písmená bez diakritiky, čísla, - _).";
    return;
  }
  try {
    await api("/api/children", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, consent_audio: $("consent").checked }),
    });
    recorder.setProcessing($("mic-processing").checked);
    await recorder.init();      // požiada o mikrofón hneď na začiatku
  } catch (err) {
    $("setup-error").textContent = err.message;
    return;
  }
  try {
    localStorage.setItem("childCode", code);
    localStorage.setItem("count", state.count);
    localStorage.setItem("rewardAt", state.rewardAt);
    localStorage.setItem("micProcessing", $("mic-processing").checked ? "1" : "");
  } catch {}

  Object.assign(state, {
    child: code,
    list: buildList(),
    index: 0, attempt: 0, position: 0, keys: 0, starsTotal: 0, rewardFound: false,
    session: (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()),
  });
  $("word-total").textContent = state.list.length;
  $("task-name").textContent = TASK_NAME[state.exercise];
  $("keys").textContent = 0;
  state.rewardAt = Math.min(state.rewardAt, state.list.length * 3);
  show("game");               // najprv zobraziť – robot sa umiestňuje podľa rozmerov políčok
  buildBoard(state.list.length * 3, state.rewardAt);
  say(`Ahoj! Dnes trénujeme hlásku ${state.words[state.phoneme].label}.`, "happy");
  showWord();
}

/* ---------------------------------------------------------- hracia plocha --- */
function buildBoard(n, goal) {
  const board = $("board");
  board.innerHTML = "";
  const cols = Math.min(n + 1, 10);
  board.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  for (let i = 0; i <= n; i++) {
    const row = Math.floor(i / cols);
    const col = row % 2 === 0 ? i % cols : cols - 1 - (i % cols);   // "hadík"
    const t = document.createElement("div");
    t.className = "tile" + (i === 0 ? " start" : "") + (i === goal ? " goal" : "");
    t.style.gridRow = row + 1;
    t.style.gridColumn = col + 1;
    t.dataset.i = i;
    t.textContent = i === goal ? "🧰" : i === 0 ? "🚩" : i === n ? "🏁" : "";
    board.appendChild(t);
  }
  const token = document.createElement("div");
  token.id = "token";
  token.textContent = "🤖";
  board.appendChild(token);
  placeToken();
}

function placeToken() {
  const tile = $("board").querySelector(`.tile[data-i="${state.position}"]`);
  const token = $("token");
  if (!tile || !token) return;
  token.style.left = `${tile.offsetLeft + tile.offsetWidth / 2}px`;
  token.style.top = `${tile.offsetTop + tile.offsetHeight / 2}px`;
  $("board").querySelectorAll(".tile").forEach((t) =>
    t.classList.toggle("visited", Number(t.dataset.i) <= state.position && Number(t.dataset.i) > 0));
}

/* robot skáče po políčkach po jednom kroku */
async function moveToken(steps) {
  const token = $("token");
  if (steps) $("board").scrollIntoView({ block: "nearest", behavior: "smooth" });
  for (let s = 0; s < steps; s++) {
    state.position++;
    placeToken();
    token.classList.remove("hop"); void token.offsetWidth; token.classList.add("hop");
    $("board").querySelector(`.tile[data-i="${state.position}"]`)?.classList.add("step");
    blip(520 + s * 120);
    await sleep(340);
    if (state.position === state.rewardAt && !state.rewardFound) {
      state.rewardFound = true;
      $("board").querySelector(".tile.goal").classList.add("found");
      say("Hurá, našiel si poklad! 🧰✨", "happy");
      chime(3);
      confetti(60);
      await sleep(1100);
    }
  }
}

/* ---------------------------------------------------------- priebeh --- */
function showWord() {
  const item = state.list[state.index];
  state.attempt = 0;
  state.last = null;
  state.prevBest = 0;
  stopPlayback();
  setOwnRecording(null);
  showCompare(false);
  $("word-index").textContent = state.index + 1;
  $("word-image").textContent = item.image;
  $("word-text").textContent = state.exercise === "word" ? item.word : item.word.toUpperCase();
  $("word-hint").textContent = item.hint || "";
  setStars(0, false);
  renderAttempts();
  $("btn-record").disabled = false;
  $("btn-retry").classList.add("hidden");
  $("btn-next").classList.add("hidden");
  $("status").textContent = state.exercise === "sound"
    ? "Najprv hlásku predvedie dospelý, potom stlač 🎤"
    : "Najprv to povie dospelý, potom stlač 🎤";
  $("adult-result").textContent = "Zatiaľ žiadny pokus.";
  setAdultButtons(false);
  $("word-card").classList.remove("pop");
}

function setStars(n, animate = true) {
  [...$("stars").children].forEach((s, i) => {
    s.textContent = i < n ? "★" : "☆";
    s.classList.toggle("lit", i < n);
    if (animate && i < n) {
      s.style.animationDelay = `${i * 0.15}s`;
      s.classList.remove("twinkle"); void s.offsetWidth; s.classList.add("twinkle");
    }
  });
}

function renderAttempts() {
  const max = state.cfg.max_attempts;
  $("attempts").innerHTML = Array.from({ length: max }, (_, i) =>
    `<span class="dot ${i < state.attempt ? "used" : ""}"></span>`).join("");
}

function setAdultButtons(on) {
  $("btn-accept").disabled = !on;
  $("btn-reject").disabled = !on;
}

async function onRecord() {
  if (state.busy) { recorder.stop(); return; }   // druhé stlačenie = stop
  stopPlayback();       // prehrávanie nesmie hrať do mikrofónu
  state.busy = true;
  // predošlý pokus o tú istú úlohu sa nestráca – počíta sa najlepší
  if (state.last && state.last.verdict !== "no_speech") {
    state.prevBest = Math.max(state.prevBest, state.last.stars);
  }
  const btn = $("btn-record");
  btn.classList.add("rec");
  $("btn-retry").classList.add("hidden");     // počas nahrávania a vyhodnocovania
  $("btn-next").classList.add("hidden");      // je na výber len mikrofón
  setAdultButtons(false);
  setStars(0, false);
  $("status").textContent = "Počúvam… (stlač znova pre stop)";
  say("Počúvam ťa 👂");

  let rec;
  try {
    rec = await recorder.record();
  } catch (err) {
    state.busy = false;
    btn.classList.remove("rec");
    $("status").textContent = err.message;
    if (state.last) showButtons(state.last);
    return;
  }
  btn.classList.remove("rec");
  if (!rec.spoke) {             // ticho: nič sa neposiela, pokus sa nepočíta
    state.busy = false;
    const prev = state.last && state.last.verdict !== "no_speech" ? state.last : null;
    if (prev) {                 // vráti stav po predošlom pokuse
      setStars(prev.stars, false);
      showButtons(prev);
      setAdultButtons(true);
      showCompare(true);
    }
    say("Nepočul som ťa. Povieš to nahlas? 🙉", "think");
    $("status").textContent = "Stlač 🎤 a povedz to nahlas";
    return;
  }
  btn.disabled = true;
  $("status").textContent = "Premýšľam…";
  say("Hmm, premýšľam… 🤔", "think");

  const item = state.list[state.index];
  state.attempt++;
  renderAttempts();
  setOwnRecording(rec.blob);
  showCompare(false);

  const fd = new FormData();
  const ext = rec.mime.includes("mp4") ? "m4a" : rec.mime.includes("ogg") ? "ogg" : "webm";
  fd.append("audio", rec.blob, `rec.${ext}`);
  fd.append("word", item.word);
  fd.append("phoneme", state.phoneme);
  fd.append("level", state.level);
  fd.append("child_code", state.child);
  fd.append("session_id", state.session);
  fd.append("attempt_no", state.attempt);
  fd.append("exercise", state.exercise);

  try {
    const res = await api("/api/recognize", {
      method: "POST", body: fd, timeout: state.cfg.recognize_timeout_seconds,
    });
    state.last = res;
    if (res.verdict === "no_speech") {   // ticho sa nepočíta ako pokus
      state.attempt--;
      renderAttempts();
    }
    showResult(res.stars, res);
  } catch (err) {
    state.attempt--;              // technická chyba sa nepočíta ako pokus
    renderAttempts();
    if (state.last) showButtons(state.last);    // vráti tlačidlá podľa predošlého pokusu
    $("status").textContent = `Chyba: ${err.message}`;
    say("Niečo sa pokazilo. Skúsime to ešte raz?", "think");
    btn.disabled = false;
  } finally {
    state.busy = false;
  }
}

function showResult(stars, res) {
  setStars(stars);
  chime(stars);
  const left = state.attempt < state.cfg.max_attempts;

  if (res.verdict === "no_speech" && stars === 0) {
    say("Nepočul som ťa. Povieš to nahlas? 🙉", "think");
  } else if (stars >= 1 && soundReplaced(res)) {
    // hláska bola nahradená: pochvala za snahu + nápoveda, nikdy výčitka
    say(left ? `Dobre! Skúsime ešte krajšie ${state.words[state.phoneme].label}? ${"⭐".repeat(stars)}`
             : `Dobre! ${"⭐".repeat(stars)}`, "cheer");
  } else if (stars >= 1) {
    say(`${pick(PRAISE)} ${"⭐".repeat(stars)}${stars < 3 && left ? " Chceš skúsiť na tri?" : ""}`, "happy");
    $("word-card").classList.add("pop");
    if (stars === 3) confetti(24);
  } else {
    // robot povzbudzuje vždy – nehodnotí dieťa negatívne
    say(pick(ENCOURAGE), "cheer");
  }

  showButtons(res);
  if (res.manual_override === undefined) renderAdult(res);
  setAdultButtons(true);
  showCompare(res.verdict !== "no_speech");
}

/* dospelý výslovnosť uznal → hláska sa už nepovažuje za nahradenú */
const soundReplaced = (res) => res.target_sound_ok === false && res.manual_override !== 1;

/* Čo môže dieťa urobiť po pokuse:
 *  - skúsiť znova: kým nemá 3 hviezdičky a zostávajú pokusy (počíta sa najlepší pokus);
 *  - ísť ďalej: má aspoň jednu hviezdičku (aj z predošlého pokusu) alebo minulo pokusy. */
function showButtons(res) {
  const noSpeech = res.verdict === "no_speech";
  const left = state.attempt < state.cfg.max_attempts;
  const best = Math.max(res.stars, state.prevBest);
  const canRetry = !noSpeech && left && res.stars < 3;
  const canNext = best >= 1 || (!noSpeech && !left);
  $("btn-record").disabled = !(noSpeech || canRetry);
  $("btn-retry").classList.toggle("hidden", !canRetry);
  $("btn-next").classList.toggle("hidden", !canNext);
  $("btn-next").textContent = best >= 1 ? `Ďalej ➜ (+${best})` : "Ďalšie slovo ➜";
  $("status").textContent = noSpeech ? "Stlač 🎤 a povedz to nahlas"
    : canRetry && canNext ? "Skús to znova, alebo choď ďalej"
    : canRetry ? "Stlač 🎤 a skús to znova"
    : best >= 1 ? "" : "Toto si dáme nabudúce.";
}

function renderAdult(res) {
  const sound = state.words[state.phoneme].label;
  const pct = (x) => `${Math.round(x * 100)} %`;
  const ph = res.phonemes;
  const MODE = { word: "slovo", phoneme: "hlásky", hybrid: "slovo + hláska", text_fallback: "len prepis (bez fonémového modelu)" };
  const wordPart = res.mode === "phoneme" ? "" : `
    <div><b>Model počul:</b> „${esc(res.recognized_text || "—")}“</div>
    <div>Porovnané slovo: <b>${esc(res.matched_word || "—")}</b> ·
      podobnosť ${pct(res.similarity)} · istota modelu ${pct(res.confidence)}</div>`;
  const phPart = !ph ? "" : `
    <div><b>Hlásky:</b> očakávané /${esc(ph.expected)}/ · rozpoznané /${esc(ph.recognized || "—")}/</div>
    <div>Cieľová hláska ${sound}: <b>${esc(ph.summary || "—")}</b> ·
      podobnosť ${pct(ph.similarity)} · istota ${pct(ph.confidence)}</div>`;
  $("adult-result").innerHTML = `${wordPart}${phPart}
    <div>Hláska ${sound}: ${res.target_sound_ok ? "✓ v poriadku" : "✗ nahradená alebo vynechaná"} ·
      skóre <b>${res.score}</b> → ${"★".repeat(res.stars)}${"☆".repeat(3 - res.stars)} ·
      ${res.latency_ms} ms · režim: ${MODE[res.mode] || res.mode}</div>
    <div class="hint">Rozpoznávanie detskej reči nie je spoľahlivé – ak počujete inak, opravte hodnotenie.</div>`;
}

async function adultOverride(correct) {
  if (!state.last || state.busy) return;
  try {
    const row = await api(`/api/attempts/${state.last.attempt_id}/override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ correct }),
    });
    if (!correct) state.prevBest = 0;   // „neuznať“ ruší aj hviezdičky z predošlých pokusov
    state.last.stars = row.final_stars;
    state.last.manual_override = row.manual_override;
    showResult(row.final_stars, state.last);
    $("adult-result").insertAdjacentHTML("beforeend",
      `<div class="hint"><b>Dospelý ${correct ? "uznal" : "neuznal"} výslovnosť.</b></div>`);
  } catch (err) {
    $("status").textContent = `Chyba: ${err.message}`;
  }
}

async function nextWord() {
  const stars = Math.max(state.last ? state.last.stars : 0, state.prevBest);
  $("btn-next").classList.add("hidden");
  $("btn-retry").classList.add("hidden");
  $("btn-record").disabled = true;
  setAdultButtons(false);
  if (stars >= 1) {
    state.keys++;
    $("keys").textContent = state.keys;
  }
  state.starsTotal += stars;
  const hadReward = state.rewardFound;
  await moveToken(stars);

  state.index++;
  if (state.index >= state.list.length) return finish();
  showWord();
  if (hadReward || !state.rewardFound) say(pick(["Ďalšie slovo!", "Ideme ďalej!", "Pozri, čo je tu!"]));
}

function finish() {
  const n = state.list.length;
  const max = n * 3;
  const won = state.starsTotal >= state.rewardAt;
  const TIER_NAME = { common: "bežná", rare: "vzácna", legendary: "legendárna" };
  let tier = "common";
  if (won) {
    // vzácnosť odmeny podľa priemeru hviezdičiek nad hranicou pokladu
    const avg = state.starsTotal / Math.max(n, 1);
    const r = Math.random() * 3;
    tier = r < avg - 1.5 ? "legendary" : r < avg ? "rare" : "common";
  }
  $("end-title").textContent = won ? "Poklad je tvoj!" : "Skoro! Poklad počká.";
  // bez pokladu dostane dieťa aspoň malú nálepku za snahu
  const icon = pick(REWARDS[tier]);
  addSticker(state.child, icon, tier);
  const total = renderAlbum("album-end", "album-end-list", state.child, true);
  $("album-end-title").textContent = `Tvoje nálepky (${total})`;
  $("reward").innerHTML = `<span class="reward-icon">${icon}</span>
    <span class="tier ${tier}">${won ? `${TIER_NAME[tier]} odmena` : "nálepka za snahu"}</span>`;
  $("summary").textContent = won
    ? `Precvičené úlohy: ${n} · hviezdičky: ${state.starsTotal} z ${max} · kľúče: ${state.keys}`
    : `Nazbieral si ${state.starsTotal} z ${max} ★, poklad bol na políčku ${state.rewardAt}. Skúsime to znova?`;
  show("end");
  const chest = $("chest");
  chest.classList.remove("open", "closed"); void chest.offsetWidth;
  chest.classList.add(won ? "open" : "closed");
  chime(won ? 3 : 1);
  if (won) confetti(90);
}

/* ---------------------------------------------------------- udalosti --- */
$("btn-start").onclick = startGame;
$("btn-record").onclick = onRecord;
$("btn-retry").onclick = onRecord;       // hneď začne nahrávať, netreba hľadať mikrofón
$("btn-next").onclick = nextWord;
$("btn-play-own").onclick = playOwn;
$("btn-accept").onclick = () => adultOverride(true);
$("btn-reject").onclick = () => adultOverride(false);
const toSetup = () => { stopPlayback(); show("setup"); $("child-code").oninput(); };
$("btn-quit").onclick = () => { if (confirm("Ukončiť hru?")) toSetup(); };
$("btn-again").onclick = toSetup;
window.addEventListener("resize", placeToken);
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && $("screen-game").classList.contains("active") &&
      !$("btn-record").disabled && document.activeElement.tagName !== "INPUT") {
    e.preventDefault();
    onRecord();
  }
});

initSetup().catch((err) => ($("setup-error").textContent = `Server neodpovedá: ${err.message}`));
