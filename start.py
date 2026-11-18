#!/usr/bin/env python3
"""
Rečová cesta – spustenie a ovládanie z konzoly.

    python start.py                 ponuka nastavení (model Whisper, fonémy, port…), potom štart
    python start.py --model medium  parametre priamo, bez ponuky
    python start.py --rychlo        bez ponuky, s naposledy použitými nastaveniami
    (alebo dvojklik na „Spustit hru.command“ / „Spustit hru.bat“)

Čo urobí:
  1. vytvorí virtuálne prostredie .venv v priečinku hry (len prvýkrát),
  2. nainštaluje knižnice z requirements.txt a requirements-phoneme.txt
     (len prvýkrát alebo keď sa tieto súbory zmenia),
  3. spustí server, otvorí hru v prehliadači a čaká na príkazy
     (o = otvoriť hru, t = panel pre logopéda, s = stav, q = ukončiť).

Nastavenia sa pamätajú v data/start.json. Používa len štandardnú knižnicu
Pythonu, takže beží aj pred inštaláciou čohokoľvek.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
STAMP = VENV / ".nainstalovane"
SETTINGS = ROOT / "data" / "start.json"
MIN_PY = (3, 10)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
WHISPER_NOTE = {
    "tiny": "≈ 75 MB, najrýchlejší, najmenej presný",
    "base": "≈ 150 MB",
    "small": "≈ 0,5 GB, predvolený – dobrý pomer rýchlosti a presnosti",
    "medium": "≈ 1,5 GB, presnejší, pomalší na CPU",
    "large-v3-turbo": "≈ 1,6 GB, presný a pomerne rýchly (odporúčané s GPU)",
    "large-v3": "≈ 3 GB, najpresnejší, na CPU veľmi pomalý",
}
DEVICES = ["auto", "cpu", "cuda"]

DEFAULTS = {
    "model": "small",        # model Whisper pre slová
    "phonemes": True,        # fonémový model (PyTorch) pre hlásky a slabiky
    "device": "auto",        # auto | cpu | cuda
    "port": 8000,
    "network": False,        # True = HOST=0.0.0.0 (tablet v tej istej sieti)
    "strict": False,         # True = pri nahradenej hláske 0 hviezdičiek
    "browser": True,         # otvoriť prehliadač po štarte
    "fast": False,           # True = Whisper v int8 (rýchlejší na slabšom CPU, prepis sa môže mierne líšiť)
}


def say(msg: str) -> None:
    print(f"[Rečová cesta] {msg}", flush=True)


# ------------------------------------------------------------ nastavenia ---

def load_settings() -> dict:
    cfg = dict(DEFAULTS)
    try:
        saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg


def save_settings(cfg: dict) -> None:
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def ask(prompt: str, default: str = "") -> str:
    try:
        return input(prompt).strip() or default
    except EOFError:
        return default


def choose(title: str, options: list[str], current: str, notes: dict | None = None) -> str:
    print(f"\n{title}")
    for i, o in enumerate(options, 1):
        mark = "●" if o == current else "○"
        note = f"   {notes[o]}" if notes and o in notes else ""
        print(f"  {i}) {mark} {o}{note}")
    ans = ask(f"Číslo alebo vlastný názov [{current}]: ", current)
    return options[int(ans) - 1] if ans.isdigit() and 1 <= int(ans) <= len(options) else ans


def yes_no(title: str, current: bool) -> bool:
    ans = ask(f"{title} (a/n) [{'a' if current else 'n'}]: ").lower()
    return current if not ans else ans.startswith(("a", "y", "1"))


def menu(cfg: dict) -> dict | None:
    """Interaktívna ponuka. Vráti nastavenia alebo None (koniec)."""
    while True:
        print("\n" + "═" * 56)
        print("  REČOVÁ CESTA – nastavenia spustenia")
        print("═" * 56)
        print(f"  1) Model Whisper (slová):      {cfg['model']}")
        print(f"  2) Fonémový model (hlásky):    {'zapnutý' if cfg['phonemes'] else 'vypnutý'}")
        print(f"  3) Zariadenie:                 {cfg['device']}")
        print(f"  4) Port:                       {cfg['port']}")
        print(f"  5) Prístup z iných zariadení:  {'áno (0.0.0.0)' if cfg['network'] else 'nie (len tento počítač)'}")
        print(f"  6) Prísne hodnotenie:          {'áno (0 ★ pri chybnej hláske)' if cfg['strict'] else 'nie (max. 1 ★)'}")
        print(f"  7) Otvoriť prehliadač:         {'áno' if cfg['browser'] else 'nie'}")
        print(f"  8) Výpočet int8 (slabší PC):   {'áno' if cfg['fast'] else 'nie'}")
        print("─" * 56)
        print("  Enter = spustiť hru      q = koniec")
        ans = ask("> ").lower()
        if ans == "":
            return cfg
        if ans in ("q", "quit", "exit", "k"):
            return None
        if ans == "1":
            cfg["model"] = choose("Model Whisper pre slová:", WHISPER_MODELS, cfg["model"], WHISPER_NOTE)
        elif ans == "2":
            cfg["phonemes"] = yes_no("Načítať fonémový model (PyTorch ≈ 1 GB + model ≈ 1,2 GB)?", cfg["phonemes"])
        elif ans == "3":
            cfg["device"] = choose("Zariadenie pre modely:", DEVICES, cfg["device"],
                                   {"auto": "GPU ak je dostupná, inak CPU", "cuda": "len NVIDIA GPU"})
        elif ans == "4":
            p = ask(f"Port [{cfg['port']}]: ", str(cfg["port"]))
            if p.isdigit() and 1 <= int(p) <= 65535:
                cfg["port"] = int(p)
        elif ans == "5":
            cfg["network"] = yes_no("Povoliť prístup z tabletu/telefónu v tej istej sieti?", cfg["network"])
            if cfg["network"]:
                print("  Pozor: mikrofón v prehliadači funguje mimo localhost len cez HTTPS (pozri README).")
        elif ans == "6":
            cfg["strict"] = yes_no("Prísne hodnotenie – 0 hviezdičiek pri nahradenej hláske?", cfg["strict"])
        elif ans == "7":
            cfg["browser"] = yes_no("Otvoriť hru v prehliadači po štarte?", cfg["browser"])
        elif ans == "8":
            print("  Whisper počíta v int8 – na bežnom notebooku s Windows býva výrazne rýchlejší,")
            print("  prepis sa však občas mierne líši. Ak je hra aj tak pomalá, zvoľte model base.")
            cfg["fast"] = yes_no("Počítať Whisper v int8?", cfg["fast"])


def environment(cfg: dict) -> dict:
    env = dict(os.environ)
    env.setdefault("ASR_MODEL", cfg["model"])
    env.setdefault("WHISPER_DEVICE", cfg["device"])
    env.setdefault("PORT", str(cfg["port"]))
    env.setdefault("HOST", "0.0.0.0" if cfg["network"] else "127.0.0.1")
    env.setdefault("MISSING_TARGET_MAX_STARS", "0" if cfg["strict"] else "1")
    if not cfg["phonemes"]:
        env.setdefault("PHONEME_MODEL", "none")
    if cfg["fast"]:
        env.setdefault("WHISPER_COMPUTE_TYPE", "int8")
    return env


# ------------------------------------------------------------ inštalácia ---

def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv() -> Path:
    py = venv_python()
    if not py.exists():
        say(f"Vytváram virtuálne prostredie v {VENV} …")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    return py


def ensure_packages(py: Path, with_phonemes: bool) -> None:
    files = [ROOT / "requirements.txt"] + ([ROOT / "requirements-phoneme.txt"] if with_phonemes else [])
    h = hashlib.sha1(f"{sys.version_info[:2]}".encode())
    for f in files:
        h.update(f.name.encode() + f.read_bytes())
    want = h.hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == want:
        return
    say("Inštalujem knižnice (prvýkrát to trvá niekoľko minút, PyTorch má okolo 1 GB) …")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"], cwd=ROOT)
    cmd = [str(py), "-m", "pip", "install"]
    for f in files:
        cmd += ["-r", str(f)]
    subprocess.check_call(cmd, cwd=ROOT)
    STAMP.write_text(want)
    say("Knižnice sú nainštalované.")


# ------------------------------------------------------------ server ---

def fetch_config(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url + "api/config", timeout=2) as r:
            return json.load(r)
    except Exception:
        return None


def wait_and_open(url: str, open_browser: bool, timeout: float = 900) -> None:
    """Počká, kým server odpovedá (modely sa môžu sťahovať), potom otvorí prehliadač."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fetch_config(url):
            break
        time.sleep(1)
    else:
        return
    say(f"Hra beží: {url}   ·   panel pre logopéda: {url}terapeut")
    print_help()
    if open_browser:
        webbrowser.open(url)


def print_help() -> None:
    print("  Príkazy:  o = otvoriť hru   t = panel pre logopéda   s = stav   h = pomoc   q = ukončiť", flush=True)


def show_status(url: str, cfg: dict) -> None:
    c = fetch_config(url)
    if not c:
        say("Server zatiaľ neodpovedá (modely sa načítavajú).")
        return
    say(f"Model pre slová: {c.get('model') or '–'}   ·   fonémový model: {c.get('phoneme_model') or '–'}")
    if c.get("phoneme_error"):
        say(f"  ⚠ fonémy: {c['phoneme_error']}")
    say(f"Adresa: {url}   ·   port {cfg['port']}   ·   prísne hodnotenie: {'áno' if cfg['strict'] else 'nie'}")


def console_loop(proc: subprocess.Popen, url: str, cfg: dict) -> None:
    """Číta príkazy z konzoly, kým server beží."""
    while proc.poll() is None:
        try:
            cmd = input().strip().lower()
        except EOFError:
            proc.wait()
            return
        if cmd in ("q", "quit", "exit", "k", "koniec"):
            return
        if cmd in ("o", "open", "hra"):
            webbrowser.open(url)
        elif cmd in ("t", "terapeut", "panel"):
            webbrowser.open(url + "terapeut")
        elif cmd in ("s", "stav", "status"):
            show_status(url, cfg)
        elif cmd in ("h", "?", "help", "pomoc"):
            print_help()
        elif cmd:
            print(f"  Neznámy príkaz „{cmd}“.", flush=True); print_help()


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    say("Server je zastavený.")


# ------------------------------------------------------------ hlavný program ---

def parse_args(cfg: dict) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Spustí hru Rečová cesta. Bez parametrov sa zobrazí ponuka nastavení.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Pamätané nastavenia: " + str(SETTINGS))
    ap.add_argument("--model", metavar="MODEL",
                    help=f"model Whisper pre slová: {', '.join(WHISPER_MODELS)} (teraz: {cfg['model']})")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fonemy", dest="phonemes", action="store_true", default=None, help="zapnúť fonémový model")
    g.add_argument("--bez-fonem", dest="phonemes", action="store_false", help="bez PyTorch a fonémového modelu")
    ap.add_argument("--device", choices=DEVICES, help="zariadenie pre modely")
    ap.add_argument("--port", type=int)
    ap.add_argument("--siet", dest="network", action="store_true", default=None,
                    help="prístup z iných zariadení v sieti (HOST=0.0.0.0)")
    ap.add_argument("--prisne", dest="strict", action="store_true", default=None,
                    help="0 hviezdičiek pri nahradenej hláske")
    ap.add_argument("--bez-prehliadaca", dest="browser", action="store_false", default=None,
                    help="neotvárať prehliadač")
    ap.add_argument("--int8", dest="fast", action="store_true", default=None,
                    help="Whisper v int8 – rýchlejší na slabšom počítači")
    ap.add_argument("--rychlo", action="store_true",
                    help="bez ponuky, s naposledy použitými nastaveniami")
    ap.add_argument("--menu", action="store_true", help="vždy zobraziť ponuku (aj s parametrami)")
    return ap.parse_args()


def main() -> int:
    if sys.version_info < MIN_PY:
        say(f"Treba Python {MIN_PY[0]}.{MIN_PY[1]} alebo novší, máte {sys.version.split()[0]}. "
            "Stiahnite ho z https://www.python.org/downloads/")
        return 1

    cfg = load_settings()
    args = parse_args(cfg)
    given = {k: v for k, v in vars(args).items() if k in DEFAULTS and v is not None}
    cfg.update(given)
    if args.model and args.model not in WHISPER_MODELS:
        say(f"Model „{args.model}“ nie je v zozname – použije sa ako vlastný názov / cesta.")

    interactive = sys.stdin.isatty()
    if args.menu or (interactive and not given and not args.rychlo):
        cfg = menu(cfg)
        if cfg is None:
            return 0
    save_settings(cfg)

    try:
        py = ensure_venv()
        ensure_packages(py, with_phonemes=cfg["phonemes"])
    except subprocess.CalledProcessError:
        say("Inštalácia knižníc zlyhala – pozrite chybu vyššie. Bez internetu sa prvé "
            "spustenie nepodarí. Skúste znova, prípadne s voľbou --bez-fonem.")
        return 1

    env = environment(cfg)
    url = f"http://127.0.0.1:{cfg['port']}/"
    say(f"Spúšťam server: model {cfg['model']}, fonémy {'áno' if cfg['phonemes'] else 'nie'}, "
        f"port {cfg['port']} (prvýkrát sa sťahujú modely, môže to trvať niekoľko minút) …")
    proc = subprocess.Popen([str(py), "server.py"], cwd=ROOT, env=env)
    threading.Thread(target=wait_and_open, args=(url, cfg["browser"]), daemon=True).start()
    try:
        if interactive:
            console_loop(proc, url, cfg)
        else:
            proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        code = proc.poll()
        stop(proc)
    if code not in (None, 0):
        say("Server sa zastavil s chybou (pozrite vyššie). Pri prvom spustení treba "
            "internet na stiahnutie modelov; obsadený port zmeníte voľbou --port 8001.")
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())

