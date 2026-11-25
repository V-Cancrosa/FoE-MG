"""Transkrypcja nagranej sesji (faster-whisper, lokalnie, po polsku).

Użycie:
    python transkrybuj.py                       # ostatnia sesja z folderu nagrania/
    python transkrybuj.py nagrania/2026-11-24_1913
    python transkrybuj.py --plik nagranie.mp3 --mowca "Stół"   # dowolny plik audio/wideo
    python transkrybuj.py --model small         # szybciej, gorzej (tiny/base/small/medium/large-v3/large-v3-turbo)

Wynik w katalogu sesji: transkrypcja.md i transkrypcja.txt, ścieżki MG i Discord scalone po czasie.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

TU = Path(__file__).resolve().parent
AUDIO = (".flac", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".mp4", ".mkv", ".webm")
SKLEJ_PRZERWA = 2.5   # s: kolejne wypowiedzi tej samej osoby bliżej niż tyle łączymy w jedną linię
SKLEJ_MAX = 40.0      # s: ale jedna linia nie dłuższa niż tyle
JSON_POSTEP = False   # True: postęp jako linie „@@{json}” dla okna Sesja.pyw


@dataclass
class Wypowiedz:
    start: float
    koniec: float
    mowca: str
    tekst: str


# ---------------------------------------------------------------- scalanie i zapis (bez whispera)
def scal(wypowiedzi: list[Wypowiedz]) -> list[Wypowiedz]:
    """Sortuje po czasie i skleja krótkie, sąsiednie kawałki tej samej osoby."""
    wynik: list[Wypowiedz] = []
    for w in sorted(wypowiedzi, key=lambda w: (w.start, w.mowca)):
        t = w.tekst.strip()
        if not t:
            continue
        o = wynik[-1] if wynik else None
        if (o and o.mowca == w.mowca and w.start - o.koniec <= SKLEJ_PRZERWA
                and w.koniec - o.start <= SKLEJ_MAX):
            o.tekst += " " + t
            o.koniec = max(o.koniec, w.koniec)
        else:
            wynik.append(Wypowiedz(w.start, w.koniec, w.mowca, t))
    return wynik


def hms(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def zapisz(katalog: Path, linie: list[Wypowiedz], meta: dict, nazwa: str = "transkrypcja"):
    tytul = meta.get("nazwa") or katalog.name
    start = meta.get("start", "")
    naglowek = [f"# Transkrypcja: {tytul}", ""]
    if start:
        naglowek.append(f"Początek nagrania: {start.replace('T', ' ')}  ")
    naglowek += [f"Model: {meta.get('model', '?')} · ścieżki: {', '.join(meta.get('mowcy', []))}", "",
                 "Czas [gg:mm:ss] liczony od początku nagrania."
                 + ("" if meta.get("tryb") == "bot" else " „Discord” to wszyscy gracze razem."), ""]
    md = naglowek + [f"**[{hms(w.start)}] {w.mowca}:** {w.tekst}  " for w in linie]
    txt = [f"[{hms(w.start)}] {w.mowca}: {w.tekst}" for w in linie]
    (katalog / f"{nazwa}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (katalog / f"{nazwa}.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    # surowe segmenty — przydają się, gdyby trzeba było scalić inaczej
    (katalog / f"{nazwa}.json").write_text(json.dumps(
        [w.__dict__ for w in linie], ensure_ascii=False, indent=1), encoding="utf-8")


def cfg() -> dict:
    p = TU / "ustawienia.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def etykieta(sciezka: dict, postacie: dict) -> str:
    """Nazwa mówcy: mapowanie z ustawień (nick → postać) po nazwie na serwerze albo loginie."""
    mapa = {k.lower(): v for k, v in (postacie or {}).items()}
    for klucz in (sciezka.get("etykieta", ""), sciezka.get("uzytkownik", ""), sciezka.get("id", "")):
        if klucz and klucz.lower() in mapa:
            return mapa[klucz.lower()]
    return sciezka.get("etykieta") or sciezka.get("plik", "?")


def postep(**kw):
    if JSON_POSTEP:
        print("@@" + json.dumps(kw, ensure_ascii=False), flush=True)


def slownik() -> str:
    p = TU / "slownik.txt"
    if not p.exists():
        return ""
    slowa = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    return ", ".join(slowa)


# ---------------------------------------------------------------- whisper
def dll_cuda_windows():
    """Pakiety nvidia-cublas/cudnn z pip trzymają DLL-e w site-packages/nvidia/*/bin — pokaż je Windowsowi."""
    if sys.platform != "win32":
        return
    for sp in map(Path, sys.path):
        nv = sp / "nvidia"
        if nv.is_dir():
            for bin_ in nv.glob("*/bin"):
                os.add_dll_directory(str(bin_))
                os.environ["PATH"] = str(bin_) + os.pathsep + os.environ.get("PATH", "")


def zaladuj_model(nazwa: str, urzadzenie: str):
    from faster_whisper import WhisperModel
    import ctranslate2
    import numpy as np

    cuda = urzadzenie in ("auto", "cuda") and ctranslate2.get_cuda_device_count() > 0
    if urzadzenie == "cuda" and not cuda:
        print("! Nie widzę karty NVIDIA z CUDA — liczę na procesorze.")
    proby = []
    if cuda:
        proby.append(("cuda", "float16", nazwa if nazwa != "auto" else "large-v3"))
    proby.append(("cpu", "int8", nazwa if nazwa != "auto" else "medium"))
    for dev, typ, mod in proby:
        try:
            print(f"Ładuję model {mod} ({dev}, {typ})… pierwszy raz pobiera się z internetu (do ~3 GB).")
            m = WhisperModel(mod, device=dev, compute_type=typ)
            list(m.transcribe(np.zeros(16000, dtype=np.float32), language="pl")[0])  # test bibliotek CUDA
            return m, mod, dev
        except Exception as e:
            print(f"! {dev} nie zadziałało: {e}")
    sys.exit("Nie udało się uruchomić modelu.")


def transkrybuj_plik(model, plik: Path, mowca: str, prompt: str, przesuniecie: float = 0.0):
    segmenty, info = model.transcribe(
        str(plik), language="pl", vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        hotwords=prompt or None,  # słownik podpowiadany w każdym oknie (initial_prompt działa tylko na początku)
        condition_on_previous_text=False,  # mniej „zapętleń” na długich nagraniach
        beam_size=5)
    dlugosc = info.duration or 1
    t_start = time.time()
    wynik = []
    for s in segmenty:
        wynik.append(Wypowiedz(s.start + przesuniecie, s.end + przesuniecie, mowca, s.text))
        ile = s.end / dlugosc
        uplynelo = time.time() - t_start
        zostalo = uplynelo / ile - uplynelo if ile > 0.01 else 0
        if JSON_POSTEP:
            postep(mowca=mowca, ile=round(ile, 4), zostalo=hms(zostalo))
        else:
            print(f"\r  {mowca}: {ile:5.1%}  [{hms(s.end)} / {hms(dlugosc)}]  zostało ok. {hms(zostalo)}   ",
                  end="", flush=True)
    if not JSON_POSTEP:
        print()
    return wynik


def ostatnia_sesja() -> Path:
    folder = Path(cfg().get("folder_nagran") or TU / "nagrania")
    sesje = sorted(p for p in folder.glob("*") if (p / "sesja.json").exists())
    if not sesje:
        sys.exit(f"Brak nagrań w {folder}. Najpierw nagrywaj.bat.")
    return sesje[-1]


def pliki_sesji(katalog: Path, meta: dict, postacie: dict | None = None) -> list[tuple[Path, str]]:
    out = []
    for s in meta.get("sciezki", []):
        for ext in (".flac", ".wav"):
            p = katalog / (s["plik"] + ext)
            if p.exists():
                out.append((p, etykieta(s, postacie or {})))
                break
    return out


def main():
    ap = argparse.ArgumentParser(description="Transkrypcja sesji (faster-whisper)")
    ap.add_argument("katalog", nargs="?", help="katalog sesji (domyślnie ostatni w nagrania/)")
    ap.add_argument("--plik", action="append", default=[], help="dowolny plik audio/wideo (można kilka razy)")
    ap.add_argument("--mowca", action="append", default=[], help="etykieta dla kolejnego --plik")
    ap.add_argument("--model", default="auto", help="auto / tiny / base / small / medium / large-v3 / large-v3-turbo")
    ap.add_argument("--urzadzenie", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--postep-json", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    global JSON_POSTEP
    JSON_POSTEP = a.postep_json
    ust = cfg()
    if a.model == "auto" and ust.get("model"):
        a.model = ust["model"]

    if a.plik:
        pliki = [(Path(p), a.mowca[i] if i < len(a.mowca) else Path(p).stem) for i, p in enumerate(a.plik)]
        katalog = pliki[0][0].resolve().parent
        meta = {"nazwa": pliki[0][0].stem}
        nazwa_wyniku = f"{pliki[0][0].stem}_transkrypcja"
    else:
        katalog = Path(a.katalog) if a.katalog else ostatnia_sesja()
        meta = json.loads((katalog / "sesja.json").read_text(encoding="utf-8"))
        pliki = pliki_sesji(katalog, meta, ust.get("postacie"))
        nazwa_wyniku = "transkrypcja"
    if not pliki:
        sys.exit(f"Nie znalazłem plików audio w {katalog}.")

    dll_cuda_windows()
    model, nazwa_modelu, dev = zaladuj_model(a.model, a.urzadzenie)
    prompt = slownik()
    wszystko: list[Wypowiedz] = []
    for i, (plik, mowca) in enumerate(pliki):
        print(f"→ {plik.name} ({mowca})", flush=True)
        postep(plik_nr=i + 1, plikow=len(pliki), mowca=mowca, ile=0)
        wszystko += transkrybuj_plik(model, plik, mowca, prompt)
    meta.update(model=f"{nazwa_modelu} ({dev})", mowcy=[m for _, m in pliki])
    linie = scal(wszystko)
    zapisz(katalog, linie, meta, nazwa_wyniku)
    print(f"\nGotowe: {katalog / (nazwa_wyniku + '.md')}  ({len(linie)} wypowiedzi)")
    postep(gotowe=str(katalog / (nazwa_wyniku + ".md")))


if __name__ == "__main__":
    main()
