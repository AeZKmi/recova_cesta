/*
 * Nahrávanie z mikrofónu s automatickým zastavením po tichu.
 *
 * Zvuk sa číta ako surové vzorky (AudioWorklet) a posiela sa ako WAV 16 kHz:
 *  - mikrofón beží počas celej hry, takže sa dá pridať ~150 ms spred stlačenia
 *    tlačidla – začiatok slova (najmä „k“, „t“) sa neodreže; dlhší úsek by mohol
 *    zachytiť koniec slova, ktoré práve predviedol dospelý;
 *  - hranica „hovorí“ sa počíta z hluku miestnosti, nie je pevná;
 *  - spracovanie zvuku prehliadačom (potlačenie šumu, automatická hlasitosť)
 *    je predvolene vypnuté, lebo oslabuje sykavky Š, C, S, ktoré sa hodnotia.
 */
const WORKLET = `registerProcessor("pcm-tap", class extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(1024); this.n = 0; }
  process(inputs) {
    const ch = inputs[0][0];
    if (ch) {
      if (this.n + ch.length > this.buf.length) { this.port.postMessage(this.buf.slice(0, this.n)); this.n = 0; }
      this.buf.set(ch, this.n);
      this.n += ch.length;
    }
    return true;
  }
});`;

class VoiceRecorder {
  constructor({ maxSeconds = 5, silenceMs = 900, preRollMs = 150, processing = false, onLevel = () => {} } = {}) {
    this.maxSeconds = maxSeconds;
    this.silenceMs = silenceMs;     // ticho po reči, po ktorom sa nahrávanie zastaví
    this.preRollMs = preRollMs;     // koľko zvuku spred stlačenia tlačidla sa pridá
    this.processing = processing;   // potlačenie šumu a automatická hlasitosť prehliadača
    this.onLevel = onLevel;
    this.stream = null;
    this.ring = [];                 // posledné rámce pred nahrávaním: {data, rms}
    this.rec = null;                // stav prebiehajúceho nahrávania
  }

  async init() {
    if (this.stream) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Prehliadač nepodporuje mikrofón. Otvorte hru cez http://localhost alebo https://.");
    }
    const p = this.processing;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: p, noiseSuppression: p, autoGainControl: p, channelCount: 1 },
    });
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = this.ctx.createMediaStreamSource(this.stream);
    let tap;
    try {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      tap = new AudioWorkletNode(this.ctx, "pcm-tap");
      tap.port.onmessage = (e) => this._frame(e.data);
    } catch {                       // staršie prehliadače bez AudioWorklet
      tap = this.ctx.createScriptProcessor(1024, 1, 1);
      tap.onaudioprocess = (e) => this._frame(new Float32Array(e.inputBuffer.getChannelData(0)));
    }
    src.connect(tap);
    tap.connect(this.ctx.destination);   // výstup je ticho; uzol musí byť zapojený, aby bežal
    this.ring = [];
  }

  /** Uvoľní mikrofón (koniec hry alebo zmena nastavenia). */
  close() {
    if (this.rec) this._finish();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.stream = this.ctx = null;
    this.ring = [];
  }

  setProcessing(on) {
    if (on === this.processing) return;
    this.processing = on;
    if (this.stream) this.close();       // nové nastavenie platí pre nový prúd z mikrofónu
  }

  /* každý rámec (~20 ms) z mikrofónu */
  _frame(data) {
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    const rms = Math.sqrt(sum / data.length);
    const ms = (data.length / this.ctx.sampleRate) * 1000;
    const r = this.rec;

    if (!r) {                            // nenahráva sa: len pamäť posledných ~150 ms
      this.ring.push({ data, rms, ms });
      let total = this.ring.reduce((a, f) => a + f.ms, 0);
      while (this.ring.length && total - this.ring[0].ms >= this.preRollMs) total -= this.ring.shift().ms;
      return;
    }

    r.chunks.push(data);
    r.elapsed += ms;
    this.onLevel(Math.min(1, rms * 10));

    // hluk miestnosti: z rámcov pred stlačením, prípadne z prvých 300 ms nahrávky
    if (r.noiseMs < 300) {
      r.noise.push(rms);
      r.noiseMs += ms;
      r.floor = VoiceRecorder.percentile(r.noise, 0.2);
    } else if (rms < r.floor) {
      r.floor = 0.9 * r.floor + 0.1 * rms;        // miestnosť stíchla → hranica klesá
    }
    const threshold = Math.min(0.12, Math.max(0.006, r.floor * 3));

    if (rms > threshold) {
      r.voiceMs += ms;
      r.silence = 0;
      if (r.voiceMs >= 60) r.spoke = true;        // kratší zvuk je len cvaknutie
    } else {
      r.silence += ms;
    }
    const tooLong = r.elapsed >= this.maxSeconds * 1000;
    if (tooLong || (r.spoke && r.silence >= this.silenceMs)) this._finish();
  }

  _finish() {
    const r = this.rec;
    this.rec = null;
    this.onLevel(0);
    r.resolve(r);
  }

  /** Nahrá jednu repliku. Vráti {blob, mime, spoke} */
  async record() {
    await this.init();
    if (this.ctx.state === "suspended") await this.ctx.resume();
    const sampleRate = this.ctx.sampleRate;
    const r = await new Promise((resolve) => {
      const pre = this.ring;
      this.ring = [];
      this.rec = {
        resolve, chunks: pre.map((f) => f.data), elapsed: 0,
        noise: pre.map((f) => f.rms), noiseMs: pre.reduce((a, f) => a + f.ms, 0), floor: 0,
        voiceMs: 0, silence: 0, spoke: false,
      };
      this.rec.floor = VoiceRecorder.percentile(this.rec.noise, 0.2);
    });

    let samples = new Float32Array(r.chunks.reduce((a, c) => a + c.length, 0));
    let at = 0;
    for (const c of r.chunks) { samples.set(c, at); at += c.length; }
    let rate = sampleRate;
    try {
      samples = await VoiceRecorder.resample(samples, sampleRate, 16000);
      rate = 16000;
    } catch { /* prehliadač nevie prevzorkovať – pošle sa pôvodná frekvencia */ }

    // bez automatickej hlasitosti býva nahrávka tichá → zosilniť (najviac 8×)
    if (r.spoke) {
      let peak = 0;
      for (let i = 0; i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i]));
      const gain = peak > 0 ? Math.min(8, 0.9 / peak) : 1;
      if (gain > 1.2) for (let i = 0; i < samples.length; i++) samples[i] *= gain;
    }
    return { blob: VoiceRecorder.wav(samples, rate), mime: "audio/wav", spoke: r.spoke };
  }

  /** Ručné zastavenie (druhé stlačenie tlačidla). */
  stop() {
    if (this.rec) this._finish();
  }

  static percentile(values, p) {
    if (!values.length) return 0;
    const s = [...values].sort((a, b) => a - b);
    return s[Math.floor((s.length - 1) * p)];
  }

  /* kvalitné prevzorkovanie nechávame na prehliadač */
  static async resample(samples, from, to) {
    if (from === to || !samples.length) return samples;
    const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const off = new Offline(1, Math.ceil((samples.length * to) / from), to);
    const buf = off.createBuffer(1, samples.length, from);
    buf.getChannelData(0).set(samples);
    const src = off.createBufferSource();
    src.buffer = buf;
    src.connect(off.destination);
    src.start();
    return (await off.startRendering()).getChannelData(0);
  }

  /* WAV, 16 bitov, mono */
  static wav(samples, rate) {
    const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
    const text = (pos, s) => [...s].forEach((c, i) => view.setUint8(pos + i, c.charCodeAt(0)));
    text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVEfmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, "data"); view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const v = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }
}
