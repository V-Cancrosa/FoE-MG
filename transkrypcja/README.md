# Transkrypcja sesji

Program na Twój komputer: nagrywa sesję (Twój mikrofon i dźwięk z Discorda jako dwie osobne ścieżki),
a potem robi z tego tekst po polsku, lokalnie, bez wysyłania czegokolwiek do internetu.
Wynik wygląda tak:

```
[00:41:12] MG: Widzisz, jak przy skrzydle bramy leży twój ojciec. Komora jest pusta.
[00:41:20] Discord: Szukam matki.
```

„MG” to Ty (mikrofon), „Discord” to wszyscy gracze razem.

> **Zgoda graczy.** Zanim nagrasz, powiedz graczom, że sesja jest nagrywana i po co.
> Nagrania i transkrypcje trzymaj u siebie. Nie wrzucaj audio do repozytorium (folder `nagrania/` jest wykluczony).

## Instalacja (raz)

1. Zainstaluj **Python 3.12** z [python.org](https://www.python.org/downloads/).
   W instalatorze zaznacz **„Add python.exe to PATH”**.
2. Pobierz repozytorium (Code → Download ZIP albo `git clone`) i otwórz folder `transkrypcja`.
3. Uruchom **`instaluj.bat`**. Na końcu zapyta o kartę NVIDIA:
   - **t** — jeśli masz kartę NVIDIA (GeForce GTX 10xx lub nowszą). Transkrypcja 3 godzin zajmie wtedy kilkanaście–kilkadziesiąt minut.
   - **Enter** — liczenie na procesorze. Działa, ale 3 godziny sesji to kilka godzin liczenia (zostaw na noc).

Przy pierwszej transkrypcji program pobierze model mowy (ok. 3 GB dla `large-v3`). Potem działa bez internetu.

## Nagrywanie

1. **Graj na słuchawkach.** Z głośnikami mikrofon zbiera też głosy graczy i wszystko będzie w transkrypcji dwa razy.
2. Uruchom **`nagrywaj.bat`**. Zobaczysz dwa paski poziomu: `MG [###.......]  Discord [##........]`.
   Powiedz coś i poproś kogoś na Discordzie, żeby się odezwał — oba paski powinny drgnąć.
3. Koniec sesji: **Ctrl+C** w okienku. Program zamknie pliki i skompresuje je do FLAC.
   Jeśli komputer się wyłączy albo zamkniesz okno krzyżykiem — nagranie i tak zostaje (zapis idzie na bieżąco).

Pliki lądują w `transkrypcja\nagrania\2026-11-24_1913\`: `mikrofon.flac`, `discord.flac`, `sesja.json`.
Nazwę możesz dopisać: `nagrywaj.bat --nazwa "Sesja 1"`.

## Transkrypcja

Uruchom **`transkrybuj.bat`** — weźmie ostatnią nagraną sesję. W jej folderze powstaną:

- `transkrypcja.md` — do czytania i do przekazania Claude'owi,
- `transkrypcja.txt` — to samo, czysty tekst,
- `transkrypcja.json` — surowe kawałki z czasami.

Inne możliwości:

```
transkrybuj.bat nagrania\2026-11-24_1913          ← konkretna sesja
transkrybuj.bat --model small                     ← szybciej, gorzej (tiny / base / small / medium / large-v3 / large-v3-turbo)
transkrybuj.bat --plik "C:\nagranie.mp4" --mowca "Stół"   ← dowolny plik audio lub wideo
```

Domyślnie: `large-v3` na karcie NVIDIA, `medium` na procesorze. `large-v3-turbo` na karcie jest kilka razy szybszy i prawie tak samo dobry.

**Słownik.** W `slownik.txt` są nazwy z kampanii (Stajnia 97, Ciche Brody, Kantar, Uriel…). Whisper dostaje je jako podpowiedź
i pisze je poprawnie. Dopisuj nowe imiona po jednym w linii; trzymaj listę krótką (do ~60 słów).

## Jak dać transkrypcję Claude'owi

Najprościej: wrzuć `transkrypcja.md` do repozytorium do `content/05-dla-mg/sesje zero/` (Add file → Upload files)
i napisz, że jest. Możesz też po prostu wkleić tekst w czat.

## Ustawienia urządzeń (`ustawienia.json`)

Domyślnie (puste pola) program bierze **domyślny mikrofon** Windowsa i nagrywa **wszystko, co gra na domyślnych słuchawkach** —
czyli Discorda. Listę urządzeń pokaże `nagrywaj.bat --lista`. Wpisz fragment nazwy:

```json
{ "mikrofon": "Blue Yeti", "discord": "", "folder_nagran": "D:\\Sesje" }
```

### Muzyka z Foundry w ścieżce Discorda

Jeśli Foundry gra muzykę na tych samych słuchawkach, trafi ona do ścieżki „Discord”. Zwykle to nie problem —
whisper pomija muzykę bez słów (VAD). Jeśli przeszkadza, oddziel Discorda wirtualnym kablem:

1. Zainstaluj darmowy **VB-Audio Virtual Cable** (vb-audio.com/Cable).
2. Discord → Ustawienia → Głos i wideo → **Urządzenie wyjściowe: CABLE Input**.
3. Windows → Panel dźwięku → Nagrywanie → **CABLE Output** → Właściwości → Nasłuchiwanie →
   zaznacz **„Nasłuchuj tego urządzenia”** i wybierz swoje słuchawki (żebyś dalej słyszał graczy).
4. W `ustawienia.json`: `"discord": "wejscie:CABLE Output"`.

Teraz ścieżka „Discord” to wyłącznie gracze.

**Dlaczego tak, a nie „nagraj tylko proces Discord.exe”?** Windows 10 (2004+) potrafi to w teorii (process loopback),
ale z Pythona wymaga to ręcznego wywoływania COM i bywa kruche. Loopback słuchawek (PyAudioWPatch, WASAPI)
działa od ręki, a kabel wirtualny daje czystą ścieżkę bez pisania sterowników.

## Czego to nie robi

- **Nie rozróżnia graczy między sobą** — w ścieżce Discorda wszyscy są „Discord”. Jest to do zrobienia później:
  albo rozpoznawanie głosów (pyannote, wymaga konta Hugging Face i karty NVIDIA), albo bot nagrywający
  każdego gracza osobno (jak Craig). Claude zwykle rozpozna postacie z kontekstu.
- Nie robi transkrypcji na żywo — liczy po sesji.

## Linux / macOS

Działa minimalnie: `pip install -r requirements.txt` (Linux potrzebuje też `libportaudio2`), potem
`python nagrywaj.py --lista`, a w `ustawienia.json` jako `"discord"` wpisz nazwę urządzenia „monitor” wyjścia (PulseAudio/PipeWire).
Na macOS do dźwięku Discorda potrzebny jest BlackHole.

## Rozwiązywanie problemów

- **Pasek „Discord” stoi** — Discord gra na innym wyjściu niż domyślne. Wpisz jego nazwę w `"discord"` (z `--lista`).
- **„Nie znalazłem Pythona”** — zainstaluj ponownie z zaznaczonym „Add python.exe to PATH”.
- **Transkrypcja pisze o CUDA i przechodzi na procesor** — uruchom `instaluj.bat` jeszcze raz i odpowiedz **t**; zaktualizuj sterownik NVIDIA.
- **Powtarzające się zdania / „Dziękuję za obejrzenie”** — whisper czasem zmyśla w ciszy. VAD ogranicza to mocno; jeśli się zdarza, zgłoś mi fragment.
