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


def kompresuj(katalog: Path):
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
                print(f"  {wav.name} → {flac.name}")
        except Exception as e:  # WAV zostaje, nic nie ginie
            print(f"  (nie skompresowano {wav.name}: {e})")


def main():
    ap = argparse.ArgumentParser(description="Nagrywanie sesji: mikrofon + Discord")
    ap.add_argument("--lista", action="store_true", help="pokaż urządzenia audio")
    ap.add_argument("--nazwa", default="", help="dopisek do nazwy katalogu sesji")
    ap.add_argument("--bez-discorda", action="store_true", help="nagraj tylko mikrofon")
    ap.add_argument("--bez-kompresji", action="store_true", help="zostaw WAV zamiast FLAC")
    a = ap.parse_args()

    sys_audio = Windows() if WINDOWS else Inne()
    if a.lista:
        sys_audio.lista()
        return

    cfg = ustawienia()
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    nazwa = stamp + (f"_{a.nazwa}" if a.nazwa else "")
    katalog = Path(cfg.get("folder_nagran") or TU / "nagrania") / nazwa
    katalog.mkdir(parents=True, exist_ok=True)

    zrodla = [("MG", "mikrofon", sys_audio.mikrofon(cfg.get("mikrofon", "")))]
    if not a.bez_discorda:
        zrodla.append(("Discord", "discord", sys_audio.discord(cfg.get("discord", ""))))

    t0 = time.time()
    sciezki, strumienie = [], []
    for etykieta, plik, d in zrodla:
        rate, kan = sys_audio.parametry(d)
        s = Sciezka(etykieta, katalog / f"{plik}.wav", rate, kan, t0)
        sciezki.append(s)
        print(f"● {etykieta:8} ← {d['name']}  ({rate} Hz)")
    for (_, _, d), s in zip(zrodla, sciezki):
        strumienie.append(sys_audio.otworz(d, s))

    meta = {"start": dt.datetime.fromtimestamp(t0).isoformat(timespec="seconds"), "nazwa": a.nazwa,
            "sciezki": [{"etykieta": s.etykieta, "plik": s.wav.sciezka.stem, "rate": s.rate} for s in sciezki]}
    (katalog / "sesja.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nNagrywam do: {katalog}\nZatrzymanie: Ctrl+C (albo zamknij okno — nagranie i tak zostanie).\n")
    try:
        while True:
            time.sleep(0.5)
            czas = str(dt.timedelta(seconds=int(time.time() - t0)))
            poz = "  ".join(f"{s.etykieta} [{pasek(s.poziom)}]" for s in sciezki)
            print(f"\r{czas}  {poz}   ", end="", flush=True)
            for s in sciezki:
                s.poziom *= 0.8
    except KeyboardInterrupt:
        pass
    print("\n\nZatrzymuję…")
    for st in strumienie:
        try:
            st.stop_stream() if WINDOWS else st.stop()
            st.close()
        except Exception:
            pass
    for s in sciezki:
        s.zamknij()
    sys_audio.koniec()
    meta["koniec"] = dt.datetime.now().isoformat(timespec="seconds")
    (katalog / "sesja.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.bez_kompresji:
        print("Kompresuję do FLAC (mniej miejsca na dysku)…")
        kompresuj(katalog)
    print(f"\nGotowe. Teraz: transkrybuj.bat  (albo: python transkrybuj.py \"{katalog}\")")


if __name__ == "__main__":
    main()
