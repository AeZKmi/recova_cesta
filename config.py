"""
Nastavenia aplikácie. Všetko sa dá zmeniť premennými prostredia, napr.:

    ASR_MODEL=large-v3-turbo python server.py
    PHONEME_MODEL=none python server.py          # bez fonémového modelu

Identifikátory modelov sú opísané v asr.py.
"""
import os
from pathlib import Path

from scoring import ScoringConfig

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "attempts.sqlite3"
WORDS_PATH = DATA_DIR / "words.json"

# --- Rozpoznávanie reči -----------------------------------------------------
# Model pre slová (faster-whisper): tiny | base | small | medium | large-v3 | large-v3-turbo
ASR_MODEL = os.getenv("ASR_MODEL", "small")
# Model pre hlásky (fonémy). "none" = vypnutý; cvičenia hlások a slabík potom
# používajú len prepis slova (menej spoľahlivé).
PHONEME_MODEL = os.getenv("PHONEME_MODEL", "phoneme:facebook/wav2vec2-xlsr-53-espeak-cv-ft")
if PHONEME_MODEL.strip().lower() in ("", "none", "off", "0"):
    PHONEME_MODEL = ""
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")          # auto | cpu | cuda (všetky modely)
# int8 je rýchle na CPU; na GPU sa odporúča float16
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "default")
WHISPER_LANGUAGE = "sk"
# Užší lúč (1–2) čas takmer neskráti (merané: 0,98 s oproti 1,00 s), ale na detských
# nahrávkach mení prepis a tým aj hviezdičky (6 z 38) – preto zostáva 5.
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
# Vlákna CPU na jeden model. 0 = automaticky: keď bežia oba modely naraz, každý dostane
# polovicu jadier (inak si na Windows vlákna PyTorch a CTranslate2 navzájom prekážajú).
ASR_THREADS = int(os.getenv("ASR_THREADS", "0"))

# --- Hra ---------------------------------------------------------------------
MAX_ATTEMPTS = 3                 # pokusy na jedno slovo
MAX_RECORD_SECONDS = 5           # max. dĺžka nahrávky (aj v prehliadači)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # väčšiu nahrávku server odmietne
# po tomto čase hra prestane čakať na server (a server už takú nahrávku nespracuje)
RECOGNIZE_TIMEOUT_SECONDS = int(os.getenv("RECOGNIZE_TIMEOUT_SECONDS", "30"))

# --- Server ------------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")   # 0.0.0.0 = prístup z tabletu v sieti
PORT = int(os.getenv("PORT", "8000"))

SCORING = ScoringConfig(
    # 1 = pri nahradenej hláske ešte 1 hviezdička (povzbudenie), 0 = prísne
    missing_target_max_stars=int(os.getenv("MISSING_TARGET_MAX_STARS", "1")),
)

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
