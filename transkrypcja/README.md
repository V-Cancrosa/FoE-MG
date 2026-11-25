# Transkrypcja sesji

Program na Twój komputer z Windows: nagrywa sesję i robi z niej tekst po polsku, lokalnie (faster-whisper),
bez wysyłania nagrań do internetu. Wszystko obsługuje jedno okno **Sesja**.

```
[00:41:12] MG: Widzisz, jak przy skrzydle bramy leży twój ojciec. Komora jest pusta.
[00:41:20] Rusty (Erwin): Szukam matki.
```

Dwa tryby nagrywania:

| Tryb | Co nagrywa | Etykiety w tekście | Potrzebuje |
|---|---|---|---|
| **Lokalny** | Twój mikrofon + wszystko, co słychać z Discorda | „MG” i „Discord” (gracze razem) | nic więcej |
| **Bot Discord** | każdą osobę na kanale głosowym osobno (jak Craig) | nazwa z serwera albo postać, np. „Uriel (zychu)” | Node.js i własny bot (10 minut, niżej) |

> **Zgoda graczy.** Powiedz graczom, że sesja jest nagrywana i po co. Bot jest widoczny na kanale
> i ogłasza start nagrania. Nagrania trzymaj u siebie — folder `nagrania/` jest poza gitem.

## Instalacja (raz)

1. *(tylko dla trybu bota)* **Node.js LTS** z [nodejs.org](https://nodejs.org/) — albo przyciskiem w instalatorze.
2. Pobierz repozytorium (Code → Download ZIP) i w folderze `transkrypcja` uruchom **`instaluj.bat`**.
   Znajdzie **Pythona 3.12** (3.13 i 3.11 też przejdą), a jeśli go nie ma, zainstaluje go sam:
   przez `py install 3.12` (nowy *Python install manager*) albo przez winget.
   Potem otworzy się **okno instalatora** z listą kroków. Kliknij **Instaluj**; kartę NVIDIA wykrywa sam.
   Na końcu zrobi na pulpicie skrót **„Sesja”** i da przycisk **Uruchom Sesję**.

Nie trzeba niczego przestawiać w *Aliasach wykonywania aplikacji* ani zaznaczać „Add to PATH”.
Najnowszy Python (3.14+) nie nadaje się: `onnxruntime` i `ctranslate2`, z których korzysta faster-whisper,
nie mają jeszcze dla niego paczek (błąd *ResolutionImpossible … onnxruntime*). Instalator weźmie 3.12 obok niego, nic nie psując.
Jeśli coś się nie uda, okno pokaże, który krok padł; cały przebieg jest w `transkrypcja\instalacja.log` — ten plik można wysłać na czat.
Instalator można uruchamiać ponownie: dokończy, naprawi albo przebuduje `.venv`, jeśli powstało na złym Pythonie.

Przy pierwszej transkrypcji pobierze się model mowy (`large-v3`, ok. 3 GB). Potem działa bez internetu.
Z kartą NVIDIA 3 godziny sesji liczą się kilkanaście–kilkadziesiąt minut.

## Okno „Sesja”

1. **Źródła.** Wybierz swój mikrofon i skąd brać graczy:
   - *Wszystko ze słuchawek* — tryb lokalny (najprościej),
   - *Bot Discord — każdy gracz osobno* — tryb bota.
2. **● Start / ■ Stop.** Paski pokazują, kto mówi. Przed sesją sprawdź, czy drgają przy każdym.
   Plik zapisuje się na bieżąco — awaria komputera nie kasuje nagrania.
3. **Transkrybuj ostatnią sesję.** Pasek postępu i log. Model *auto* = `large-v3` na karcie NVIDIA, `medium` na procesorze;
   `large-v3-turbo` jest kilka razy szybszy i prawie tak samo dobry.
4. **Otwórz transkrypcję / Otwórz folder nagrań.**

Graj na **słuchawkach** — z głośnikami mikrofon zbiera graczy drugi raz.

**Słownik.** `slownik.txt` zawiera nazwy z kampanii (Stajnia 97, Ciche Brody, Kantar…). Whisper dostaje je jako
podpowiedź w każdym fragmencie nagrania. Dopisuj nowe imiona po jednym w linii (do ~60).

**Gdzie są pliki:** `transkrypcja\nagrania\2026-11-27_1900\` (tryb bota: `…_bot\`):
ścieżki `.flac`, `sesja.json`, a po transkrypcji `transkrypcja.md`, `.txt`, `.json`.

**Jak dać transkrypcję Claude'owi:** wrzuć `transkrypcja.md` do repozytorium do `content/05-dla-mg/sesje zero/`
(Add file → Upload files) albo wklej tekst w czat.

## Tryb bota: założenie bota (raz)

1. Wejdź na [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**, nazwij np. „Nagrywacz”.
2. **Bot** → **Reset Token** → skopiuj token. W oknie Sesja wklej go w pole **Token** → **Zapisz token**.
   Token trafia do `bot/token.txt`, który jest poza gitem. **Nigdy nie wrzucaj go do repozytorium ani na czat.**
   Jeśli wycieknie — znowu „Reset Token”.
3. Na tej samej stronie: **Public Bot — wyłącz** (tylko Ty go zaprosisz). **Privileged Gateway Intents — zostaw wyłączone**,
   bot ich nie potrzebuje (używa tylko Guilds i Guild Voice States).
4. **OAuth2 → URL Generator:** zakresy **bot** i **applications.commands**; uprawnienia **View Channels**, **Connect**, **Send Messages**.
   Otwórz wygenerowany link i wybierz swój serwer.
   (Albo gotowy link: `https://discord.com/oauth2/authorize?client_id=ID_APLIKACJI&scope=bot%20applications.commands&permissions=1051648`,
   ID aplikacji jest w *General Information*.)
5. W oknie Sesja: Gracze → **Bot Discord**, w polu **MG na Discordzie** wpisz swoją nazwę użytkownika, **Uruchom bota**.
   Status zmieni się na zielony z nazwą serwera.

**Na sesji:** wejdź na kanał głosowy i kliknij **● Start** (bot dołączy do Twojego kanału) — albo wpisz na Discordzie `/nagrywaj`.
Koniec: **■ Stop** albo `/stop`. Okno musi być otwarte, bo to ono uruchamia bota.

**Postacie.** W polu *Postacie* wpisz, jak nazywać ludzi w tekście — po lewej nick z serwera albo login:

```
Vulpes = MG
zychu = Uriel (zychu)
Tymianox = Rick (Tymek)
Erwin = Rusty (Erwin)
```

**Czy lokalny mikrofon jest jeszcze potrzebny?** Nie — bot nagrywa też Ciebie, bo jesteś na kanale.
Opcja *Nagrywaj też mój mikrofon lokalnie (zapas)* zapisuje kopię do podfolderu `zapas\`, której transkrypcja nie używa.
Przyda się, gdyby ścieżka bota była pusta: `.venv\Scripts\python transkrybuj.py --plik nagrania\…\zapas\mikrofon.flac --mowca MG`.

## Dlaczego bot jest w Node.js, a nie w Pythonie (stan na 25.11.2026)

Od 1 marca 2026 Discord wymaga szyfrowania end-to-end rozmów głosowych (DAVE) także od botów
([blog Discorda](https://discord.com/blog/bringing-dave-to-all-discord-platforms)). Bot musi więc umieć **odszyfrować** odbierany dźwięk.

- **py-cord** (najnowszy 2.8.1): DAVE obsługuje tylko przy *wysyłaniu*; dokumentacja ostrzega, że nagrywanie może nie działać
  ([docs 2.8.1](https://docs.pycord.dev/en/v2.8.1/api/voice.html)). Odbiór z DAVE jest w otwartym PR
  ([#3159](https://github.com/Pycord-Development/pycord/pull/3159)), nie w wydaniu; do tego davey 0.2 psuje 2.8.1
  ([zgłoszenie](https://github.com/felix920506/jellychord/issues/86)).
- **discord.py + discord-ext-voice-recv**: odbiór z DAVE tylko w nakładających się PR-ach i forkach
  ([przegląd w forku](https://github.com/Florian-85/discord-ext-voice-recv/issues/7)), bez wydania.
- **@discordjs/voice 0.19.2** (wydane 17.03.2026): opublikowany kod odbioru odszyfrowuje DAVE (`daveSession.decrypt` w `parsePacket`,
  biblioteka [@snazzah/davey](https://www.npmjs.com/package/@snazzah/davey)), a poprawka gubionego dźwięku
  ([#11419](https://github.com/discordjs/discord.js/issues/11419), [PR #11449](https://github.com/discordjs/discord.js/pull/11449))
  jest w tym wydaniu. To jedyna gotowa, wydana biblioteka z odbiorem DAVE — dlatego bot to mały proces Node uruchamiany z okna.

Zastrzeżenia: Discord nie dokumentuje odbioru dźwięku, więc biblioteka nie gwarantuje stabilności
([dokumentacja](https://discord.js.org/docs/packages/voice/main)). Wersje są przypięte (`@discordjs/voice 0.19.2`, `@snazzah/davey <0.2`);
nie aktualizuj ich bez próby. Zgłaszano, że pierwsze sekundy po wejściu bota mogą się nie odszyfrować — **włącz nagrywanie
minutę przed startem sesji**. Jeśli bot zawiedzie, tryb lokalny działa zawsze.

## Tryb lokalny: muzyka z Foundry

W trybie lokalnym ścieżka „Discord” to wszystko, co gra na słuchawkach, także muzyka z Foundry. Whisper zwykle ją pomija.
Jeśli przeszkadza, oddziel Discorda darmowym **VB-Audio Virtual Cable**: Discord → Głos i wideo → wyjście **CABLE Input**;
Windows → Dźwięk → Nagrywanie → **CABLE Output** → Właściwości → Nasłuchiwanie → „Nasłuchuj tego urządzenia” na słuchawki;
w oknie Sesja jako graczy wybierz **Wejście: CABLE Output**.

## Bez okna (konsola)

```
.venv\Scripts\python nagrywaj.py --lista
.venv\Scripts\python nagrywaj.py --nazwa "Sesja 1"
.venv\Scripts\python transkrybuj.py [katalog] [--model large-v3-turbo]
.venv\Scripts\python transkrybuj.py --plik "C:\nagranie.mp4" --mowca "Stół"
cd bot && node nagrywacz.mjs        (bot sam; sterowanie /nagrywaj i /stop)
```

Linux/macOS: działa minimalnie (sounddevice; Linux potrzebuje `libportaudio2`, Discord przez urządzenie „monitor”).

## Rozwiązywanie problemów

- **Pasek „Discord” stoi (tryb lokalny)** — Discord gra na innym wyjściu; wybierz je z listy *Wyjście: …*.
- **Bot: „Brak tokenu”** — wklej token i kliknij Zapisz token.
- **Bot nie widzi serwera** — nie został zaproszony (krok 4).
- **„Nie wiem, który kanał nagrać”** — wejdź na kanał głosowy i wpisz swoją nazwę w „MG na Discordzie”, albo użyj `/nagrywaj`.
- **Pusta ścieżka gracza w trybie bota** — problem z odszyfrowaniem (log okna pokazuje `[voice] … decrypt`). Zgłoś log; nagrywaj lokalnie.
- **CUDA nie działa, liczy na procesorze** — uruchom `instaluj.bat` jeszcze raz (zaznacz kartę NVIDIA), zaktualizuj sterownik.
  Krok *Sprawdzenie* w instalatorze mówi wprost, czy karta jest widoczna.
- **Powtarzające się zdania w ciszy** — typowa wpadka whispera; VAD mocno to ogranicza. Zgłoś fragment.
