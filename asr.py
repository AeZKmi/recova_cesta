"""
Rozpoznávanie reči – dva lokálne modely (prvýkrát sa stiahnu z Hugging Face do cache).

Model sa vyberá textovým identifikátorom:
  small, large-v3-turbo, faster-whisper:small   Whisper cez faster-whisper (slová)
  phoneme:facebook/wav2vec2-xlsr-53-espeak-cv-ft wav2vec 2.0, ktorý rozpoznáva fonémy (IPA)

Každý rozpoznávač má atribúty spec, kind ("words" | "phonemes"), load_seconds
a metódu transcribe(cesta alebo zvuk 16 kHz ako numpy pole) → slovník:
  text            – prepis (pri fonémovom modeli fonémy oddelené medzerou)
  words           – [(slovo, pravdepodobnosť)]          (prázdne pri fonémach)
  phones          – [(fonéma, pravdepodobnosť)] alebo None
  no_speech_prob  – pravdepodobnosť, že nahrávka neobsahuje reč
  duration        – dĺžka nahrávky v sekundách
  latency_ms      – čas rozpoznávania
"""
from __future__ import annotations

import json
import os
import threading
import time

import numpy as np

SAMPLE_RATE = 16_000
SPECIAL = {"<s>", "</s>", "<unk>", "<pad>", "[PAD]", "[UNK]", "|", " "}


def greedy_decode(probs: np.ndarray, id2tok: dict[int, str], blank_id: int) -> list[tuple[str, float]]:
    """
    CTC: probs (T, V) po rámcoch → [(token, priemerná pravdepodobnosť)] po zlúčení
    opakovaní; prázdny symbol, špeciálne tokeny a oddeľovače slov sa vynechajú.
    """
    out, prev, run = [], None, []
    for t, idx in enumerate([int(i) for i in probs.argmax(axis=-1)] + [None]):
        if idx != prev:
            if prev is not None and prev != blank_id and run:
                tok = id2tok.get(prev, "")
                if tok and tok not in SPECIAL:
                    out.append((tok, float(np.mean(run))))
            run = []
        if idx is not None and idx != blank_id:
            run.append(float(probs[t, idx]))
        prev = idx
    return out


def load_audio(path) -> np.ndarray:
    """webm/ogg/m4a/wav → 16 kHz mono float32 (PyAV z faster-whisper, ffmpeg netreba)."""
    from faster_whisper.audio import decode_audio
    return decode_audio(str(path), sampling_rate=SAMPLE_RATE)


class Recognizer:
    def __init__(self, spec: str, kind: str, load):
        self.spec, self.kind = spec, kind
        self._lock = threading.Lock()          # jeden model = jedna požiadavka naraz
        t0 = time.perf_counter()
        load()
        self.load_seconds = round(time.perf_counter() - t0, 1)

    def transcribe(self, audio, deadline: float | None = None) -> dict:
        """
        audio = cesta k súboru alebo už dekódovaný zvuk (16 kHz mono float32).
        deadline (time.perf_counter()): ak sa model uvoľní až po ňom, prehliadač už
        na výsledok nečaká – výpočet sa vynechá, aby sa nehromadili staré požiadavky.
        """
        if not isinstance(audio, np.ndarray):
            audio = load_audio(audio)
        with self._lock:
            if deadline is not None and time.perf_counter() > deadline:
                raise TimeoutError("požiadavka čakala príliš dlho")
            t0 = time.perf_counter()
            out = self._transcribe(audio)
            out["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        out.setdefault("words", [])
        out.setdefault("phones", None)
        return out

    def warm_up(self) -> None:
        """Prvý výpočet je pomalý (alokácie, JIT) – urobí sa pri štarte, nie pri prvom dieťati."""
        with self._lock:
            self._transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), warm=True)


class WhisperRecognizer(Recognizer):
    def __init__(self, model: str, device: str = "auto", compute_type: str = "default", threads: int = 0):
        def load():
            from faster_whisper import WhisperModel
            self.model = WhisperModel(model, device=device, compute_type=compute_type,
                                      cpu_threads=threads)
        super().__init__(model, "words", load)   # v DB zostáva krátky názov ("small")

    def _transcribe(self, audio, warm=False):
        import config
        segments, info = self.model.transcribe(
            audio,
            language=config.WHISPER_LANGUAGE,
            task="transcribe",
            beam_size=config.WHISPER_BEAM_SIZE,
            temperature=0.0,                    # deterministický výstup
            condition_on_previous_text=False,   # krátke nahrávky, bez nadväzovania
            word_timestamps=True,               # potrebné pre pravdepodobnosti slov
            vad_filter=not warm,                # odstráni ticho → menej halucinácií
            vad_parameters={"min_silence_duration_ms": 300},
            # jedno slovo má pár tokenov; pri hluku (televízor, rozhovor) by Whisper
            # inak mohol „vymýšľať“ dlhý text a na slabšom CPU počítať desiatky sekúnd
            max_new_tokens=32,
        )
        words, texts, no_speech = [], [], []
        for seg in segments:                    # generátor – až tu prebehne výpočet
            texts.append(seg.text)
            no_speech.append(seg.no_speech_prob)
            words += [(w.word.strip(), float(w.probability)) for w in seg.words or []]
        return {
            "text": " ".join(t.strip() for t in texts).strip(),
            "words": words,
            "no_speech_prob": max(no_speech) if no_speech else 1.0,
            "duration": round(float(info.duration), 2),
        }


class PhonemeRecognizer(Recognizer):
    """
    wav2vec 2.0 s CTC výstupom vo fonémach IPA. Slovník tokenov sa číta priamo
    z vocab.json, takže netreba knižnicu phonemizer/espeak.
    """

    def __init__(self, model: str, device: str = "auto", threads: int = 0):
        def load():
            import torch
            if threads:
                torch.set_num_threads(threads)
            from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC
            self.torch = torch
            self.device = device if device and device != "auto" else (
                "cuda" if torch.cuda.is_available() else "cpu")
            self.extractor = Wav2Vec2FeatureExtractor.from_pretrained(model)
            if os.path.isdir(model):                  # lokálne uložený model
                vocab_path = os.path.join(model, "vocab.json")
            else:
                from huggingface_hub import hf_hub_download
                vocab_path = hf_hub_download(model, "vocab.json")
            with open(vocab_path, encoding="utf-8") as f:
                vocab = json.load(f)
            self.id2tok = {i: t for t, i in vocab.items()}
            self.blank_id = vocab.get("<pad>", 0)
            self.model = Wav2Vec2ForCTC.from_pretrained(model).to(self.device).eval()
        super().__init__(f"phoneme:{model}", "phonemes", load)

    def _transcribe(self, audio, warm=False):
        duration = round(len(audio) / SAMPLE_RATE, 2)
        if duration < 0.1:
            return {"text": "", "phones": [], "no_speech_prob": 1.0, "duration": duration}
        inputs = self.extractor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with self.torch.no_grad():
            logits = self.model(inputs.input_values.to(self.device)).logits[0].float().cpu().numpy()
        z = np.exp(logits - logits.max(axis=-1, keepdims=True))
        phones = greedy_decode(z / z.sum(axis=-1, keepdims=True), self.id2tok, self.blank_id)
        return {"text": " ".join(t for t, _ in phones), "phones": phones,
                "no_speech_prob": 0.0 if phones else 1.0, "duration": duration}


def create_recognizer(spec: str, device: str = "auto", compute_type: str = "default",
                      threads: int = 0) -> Recognizer:
    """threads = vlákna CPU pre model (0 = predvolené knižnice)."""
    spec = (spec or "").strip()
    backend, sep, model = spec.partition(":")
    if sep and backend == "phoneme":
        return PhonemeRecognizer(model, device, threads)
    if sep and backend == "faster-whisper":
        spec = model
    if not spec:
        raise ValueError("Prázdny identifikátor modelu")
    return WhisperRecognizer(spec, device, compute_type, threads)
