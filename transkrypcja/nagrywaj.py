"""Nagrywanie sesji: mikrofon MG + dźwięk Discorda, każda ścieżka do osobnego pliku WAV.

Użycie:
    python nagrywaj.py              # nagrywa do nagrania/RRRR-MM-DD_GGMM/, stop: Ctrl+C
    python nagrywaj.py --lista      # pokazuje urządzenia audio (do ustawienia w ustawienia.json)
    python nagrywaj.py --nazwa "Sesja 1"

Pliki WAV są zapisywane na bieżąco, a nagłówek poprawiany co kilka sekund, więc nawet po
awarii prądu nagranie do ostatnich sekund nadaje się do transkrypcji.

Windows: PyAudioWPatch (WASAPI). Dźwięk Discorda to „loopback” urządzenia wyjściowego,
na które Discord gra (domyślnie: domyślne głośniki/słuchawki) albo wejście wirtualnego kabla.
Inne systemy: sounddevice (np. źródło „monitor” w PulseAudio/PipeWire).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np

TU = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
PAD_PROG = 0.25      # s: większa luka niż tyle = dopisz ciszę (loopback milczy, gdy nic nie gra)
FIX_EVERY = 5.0      # s: co ile poprawiać nagłówek WAV i robić fsync


# ---------------------------------------------------------------- zapis WAV odporny na awarię
class WavNaBiezaco:
    """Mono 16 bit. Nagłówek z aktualnymi rozmiarami dopisywany co FIX_EVERY sekund."""

    def __init__(self, sciezka: Path, rate: int):
        self.sciezka, self.rate = sciezka, rate
        self.f = open(sciezka, "wb")
        self.probki = 0
        self.lock = threading.Lock()
        self._ostatni_fix = 0.0
        self._naglowek()

    def _naglowek(self):
        dane = self.probki * 2
        self.f.seek(0)
        self.f.write(b"RIFF" + struct.pack("<I", 36 + dane) + b"WAVE")
        self.f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, self.rate, self.rate * 2, 2, 16))
        self.f.write(b"data" + struct.pack("<I", dane))
        self.f.seek(0, os.SEEK_END)

    def pisz(self, mono_i16: np.ndarray):
        with self.lock:
            self.f.write(mono_i16.astype("<i2").tobytes())
            self.probki += len(mono_i16)
            teraz = time.monotonic()
            if teraz - self._ostatni_fix > FIX_EVERY:
                self._naglowek()
                self.f.flush()
                os.fsync(self.f.fileno())
                self._ostatni_fix = teraz

    def zamknij(self):
        with self.lock:
            self._naglowek()
            self.f.flush()
            os.fsync(self.f.fileno())
            self.f.close()


class Sciezka:
    """Jedna ścieżka: przyjmuje bloki audio, miesza do mono, wyrównuje do zegara ściennego."""

    def __init__(self, etykieta: str, sciezka: Path, rate: int, kanaly: int, t0: float):
        self.etykieta, self.rate, self.kanaly, self.t0 = etykieta, rate, kanaly, t0
        self.wav = WavNaBiezaco(sciezka, rate)
        self.poziom = 0.0
        self.bloki = 0

    def _dopelnij_do(self, chwila: float, odejmij: int = 0):
        oczekiwane = int((chwila - self.t0) * self.rate) - odejmij
        brak = oczekiwane - self.wav.probki
        if brak > PAD_PROG * self.rate:
            self.wav.pisz(np.zeros(brak, dtype=np.int16))

    def blok(self, surowe: bytes | np.ndarray):
        a = np.frombuffer(surowe, dtype=np.int16) if isinstance(surowe, (bytes, bytearray)) else surowe
        if a.ndim == 1 and self.kanaly > 1:
            a = a.reshape(-1, self.kanaly)
        mono = a.mean(axis=1).astype(np.int16) if a.ndim == 2 else a.astype(np.int16)
        # WASAPI loopback nie daje żadnych bloków, gdy nic nie gra: wstaw ciszę, żeby czas się zgadzał
        self._dopelnij_do(time.time(), odejmij=len(mono))
        self.wav.pisz(mono)
        self.bloki += 1
        if len(mono):
            self.poziom = max(self.poziom * 0.7, float(np.abs(mono).max()) / 32768)

    def zamknij(self):
        self._dopelnij_do(time.time())
        self.wav.zamknij()


# ---------------------------------------------------------------- urządzenia
def ustawienia() -> dict:
    p = TU / "ustawienia.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def pasuje(nazwa: str, wzorzec: str) -> bool:
    return wzorzec.lower() in nazwa.lower()


class Windows:
    def __init__(self):
        import pyaudiowpatch as pyaudio  # tylko Windows
        self.pa_mod = pyaudio
        self.pa = pyaudio.PyAudio()
        self.wasapi = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)

    def urzadzenia(self):
        for i in range(self.pa.get_device_count()):
            d = self.pa.get_device_info_by_index(i)
            if d["hostApi"] == self.wasapi["index"]:
                yield d

    def lista(self):
        print("WEJŚCIA (mikrofony, kable wirtualne):")
        for d in self.urzadzenia():
            if d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
                print(f"  [{d['index']}] {d['name']}")
        print("\nWYJŚCIA (głośniki/słuchawki) — do nagrania Discorda przez loopback:")
        for d in self.urzadzenia():
            if d["maxOutputChannels"] > 0:
                print(f"  [{d['index']}] {d['name']}")
        dom_in = self.pa.get_device_info_by_index(self.wasapi["defaultInputDevice"])["name"]
        dom_out = self.pa.get_device_info_by_index(self.wasapi["defaultOutputDevice"])["name"]
        print(f"\nDomyślny mikrofon: {dom_in}\nDomyślne wyjście: {dom_out}")

    def nazwy(self) -> tuple[list[str], list[str]]:
        """(wejścia, wyjścia) — do list wyboru w oknie."""
        we = [d["name"] for d in self.urzadzenia() if d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice")]
        wy = [d["name"] for d in self.urzadzenia() if d["maxOutputChannels"] > 0 and not d.get("isLoopbackDevice")]
        return we, wy

    def mikrofon(self, wzorzec: str):
        if not wzorzec:
            return self.pa.get_device_info_by_index(self.wasapi["defaultInputDevice"])
        for d in self.urzadzenia():
            if d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice") and pasuje(d["name"], wzorzec):
                return d
        sys.exit(f"Nie znalazłem mikrofonu „{wzorzec}”. Sprawdź: nagrywaj.bat --lista")

    def discord(self, wzorzec: str):
        """'' = loopback domyślnego wyjścia; 'wejscie:X' = urządzenie wejściowe X (np. CABLE Output);
        inaczej = loopback wyjścia o nazwie zawierającej X."""
        if wzorzec.lower().startswith("wejscie:"):
            return self.mikrofon(wzorzec.split(":", 1)[1].strip())
        if wzorzec:
            wyj = next((d for d in self.urzadzenia() if d["maxOutputChannels"] > 0 and not d.get("isLoopbackDevice")
                        and pasuje(d["name"], wzorzec)), None)
            if not wyj:
                sys.exit(f"Nie znalazłem wyjścia „{wzorzec}”. Sprawdź: nagrywaj.bat --lista")
        else:
            wyj = self.pa.get_device_info_by_index(self.wasapi["defaultOutputDevice"])
        for lb in self.pa.get_loopback_device_info_generator():
            if wyj["name"] in lb["name"]:
                return lb
        sys.exit(f"Brak loopbacku dla „{wyj['name']}”.")

    def otworz(self, d: dict, sciezka: Sciezka):
        def cb(dane, ramki, info, status):
            sciezka.blok(dane)
            return (None, self.pa_mod.paContinue)
        s = self.pa.open(format=self.pa_mod.paInt16, channels=sciezka.kanaly, rate=sciezka.rate,
                         input=True, input_device_index=d["index"],
                         frames_per_buffer=int(sciezka.rate * 0.1), stream_callback=cb)
        s.start_stream()
        return s

    @staticmethod
    def parametry(d: dict) -> tuple[int, int]:
        # WASAPI (tryb współdzielony) chce dokładnie formatu urządzenia; do mono mieszamy sami
        return int(d["defaultSampleRate"]), max(1, int(d["maxInputChannels"]))

    def koniec(self):
        self.pa.terminate()


class Inne:
    """Linux/macOS przez sounddevice. Discord = urządzenie wejściowe (np. 'monitor' w PulseAudio)."""

    def __init__(self):
        import sounddevice as sd
        self.sd = sd

    def lista(self):
        print(self.sd.query_devices())
        print("\nLinux: dźwięk Discorda nagrasz z urządzenia „monitor” wyjścia (PulseAudio/PipeWire).")

    def _znajdz(self, wzorzec: str):
        if not wzorzec:
            return self.sd.query_devices(kind="input")
        for d in self.sd.query_devices():
            if d["max_input_channels"] > 0 and pasuje(d["name"], wzorzec):
                return d
        sys.exit(f"Nie znalazłem urządzenia „{wzorzec}”. Sprawdź: --lista")

    def nazwy(self) -> tuple[list[str], list[str]]:
        we = [d["name"] for d in self.sd.query_devices() if d["max_input_channels"] > 0]
        return we, []

    def mikrofon(self, w):
        return self._znajdz(w)

    def discord(self, w):
        if not w:
            sys.exit("Na tym systemie ustaw \"discord\" w ustawienia.json (np. \"monitor\").")
        return self._znajdz(w.split(":", 1)[1] if w.lower().startswith("wejscie:") else w)

    def otworz(self, d, sciezka: Sciezka):
        def cb(dane, ramki, czas, status):
            sciezka.blok(dane.copy())
        s = self.sd.InputStream(device=d["index"], channels=sciezka.kanaly, samplerate=sciezka.rate,
                                dtype="int16", blocksize=int(sciezka.rate * 0.1), callback=cb)
        s.start()
        return s

    @staticmethod
    def parametry(d) -> tuple[int, int]:
        return int(d["default_samplerate"]), max(1, min(2, int(d["max_input_channels"])))

    def koniec(self):
        pass


# ---------------------------------------------------------------- główna pętla
def pasek(p: float) -> str:
    n = min(10, int(p * 30))
    return "#" * n + "." * (10 - n)


def kompresuj(katalog: Path, log=print):
    try:
        import soundfile as sf
    except ImportError:
        return
    for wav in katalog.glob("*.wav"):
        flac = wav.with_suffix(".flac")
        try:
            info = sf.info(wav)
            with sf.SoundFile(flac, "w", samplerate=info.samplerate, channels=1, subtype="PCM_16") as out:
                for blok in sf.blocks(wav, blocksize=info.samplerate * 60, dtype="int16"):
                    out.write(blok)
            if sf.info(flac).frames == info.frames:
                wav.unlink()
                log(f"  {wav.name} → {flac.name}")
        except Exception as e:  # WAV zostaje, nic nie ginie
            log(f"  (nie skompresowano {wav.name}: {e})")


def zapisz_ustawienia(cfg: dict):
    (TU / "ustawienia.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def folder_nagran(cfg: dict) -> Path:
    return Path(cfg.get("folder_nagran") or TU / "nagrania")


def nowy_katalog(cfg: dict, dopisek: str = "") -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    k = folder_nagran(cfg) / (stamp + (f"_{dopisek}" if dopisek else ""))
    k.mkdir(parents=True, exist_ok=True)
    return k


def system_audio():
    return Windows() if WINDOWS else Inne()


class Nagrywanie:
    """Mikrofon (+ opcjonalnie loopback Discorda) do katalogu. Używane przez okno i przez konsolę."""

    def __init__(self, sys_audio, mikrofon: str = "", discord: str | None = ""):
        self.sa = sys_audio
        self.zrodla = [("MG", "mikrofon", sys_audio.mikrofon(mikrofon))]
        if discord is not None:
            self.zrodla.append(("Discord", "discord", sys_audio.discord(discord)))
        self.sciezki: list[Sciezka] = []
        self.strumienie = []
        self.katalog: Path | None = None
        self.t0 = 0.0

    def start(self, katalog: Path, nazwa: str = ""):
        self.katalog, self.t0 = katalog, time.time()
        for etykieta, plik, d in self.zrodla:
            rate, kan = self.sa.parametry(d)
            self.sciezki.append(Sciezka(etykieta, katalog / f"{plik}.wav", rate, kan, self.t0))
        for (_, _, d), s in zip(self.zrodla, self.sciezki):
            self.strumienie.append(self.sa.otworz(d, s))
        self.meta = {"start": dt.datetime.fromtimestamp(self.t0).isoformat(timespec="seconds"), "nazwa": nazwa,
                     "tryb": "lokalny",
                     "sciezki": [{"etykieta": s.etykieta, "plik": s.wav.sciezka.stem, "rate": s.rate} for s in self.sciezki]}
        self._zapisz_meta()

    def _zapisz_meta(self):
        (self.katalog / "sesja.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def stop(self, kompresja: bool = True, log=print):
        for st in self.strumienie:
            try:
                st.stop_stream() if WINDOWS else st.stop()
                st.close()
            except Exception:
                pass
        for s in self.sciezki:
            s.zamknij()
        self.meta["koniec"] = dt.datetime.now().isoformat(timespec="seconds")
        self._zapisz_meta()
        if kompresja:
            log("Kompresuję do FLAC (mniej miejsca na dysku)…")
            kompresuj(self.katalog, log)


def main():
    ap = argparse.ArgumentParser(description="Nagrywanie sesji: mikrofon + Discord (konsola; zwykle używaj okna Sesja.pyw)")
    ap.add_argument("--lista", action="store_true", help="pokaż urządzenia audio")
    ap.add_argument("--nazwa", default="", help="dopisek do nazwy katalogu sesji")
    ap.add_argument("--bez-discorda", action="store_true", help="nagraj tylko mikrofon")
    ap.add_argument("--bez-kompresji", action="store_true", help="zostaw WAV zamiast FLAC")
    a = ap.parse_args()

    sa = system_audio()
    if a.lista:
        sa.lista()
        return
    cfg = ustawienia()
    discord = cfg.get("discord", "")
    if a.bez_discorda or discord == "bot":
        discord = None
    n = Nagrywanie(sa, cfg.get("mikrofon", ""), discord)
    katalog = nowy_katalog(cfg, a.nazwa)
    n.start(katalog, a.nazwa)
    for (et, _, d) in n.zrodla:
        print(f"● {et:8} ← {d['name']}")
    print(f"\nNagrywam do: {katalog}\nZatrzymanie: Ctrl+C (albo zamknij okno — nagranie i tak zostanie).\n")
    try:
        while True:
            time.sleep(0.5)
            czas = str(dt.timedelta(seconds=int(time.time() - n.t0)))
            poz = "  ".join(f"{s.etykieta} [{pasek(s.poziom)}]" for s in n.sciezki)
            print(f"\r{czas}  {poz}   ", end="", flush=True)
            for s in n.sciezki:
                s.poziom *= 0.8
    except KeyboardInterrupt:
        pass
    print("\n\nZatrzymuję…")
    n.stop(not a.bez_kompresji)
    sa.koniec()
    print(f"\nGotowe. Teraz transkrypcja: python transkrybuj.py \"{katalog}\"")


if __name__ == "__main__":
    main()
