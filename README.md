# FoE-MG

Strona projektu na GitHub Pages: składa wszystkie materiały (stare, przejściowe i nowe) w jedną spójną całość.
Generuje się automatycznie z katalogu `content/` przy każdym pushu na `main`.

## Jak to działa

```
content/
├── _site.json          ← tytuł, podtytuł i stopka strony
├── _index.md           ← tekst powitalny na stronie głównej
├── 01-stare/           ← etap 1
│   ├── _info.md        ← tytuł, okres i opis etapu (opcjonalnie)
│   └── …dowolne pliki i podkatalogi…
├── 02-pomiedzy/        ← etap 2
└── 03-nowe/            ← etap 3
```

- **Każdy katalog w `content/` to jeden etap.** Kolejność wynika z numeru na początku nazwy
  (`01-`, `02-`, `03-`…). Można dodawać nowe etapy, np. `02a-wersja-testowa`.
- **Podkatalogi** wewnątrz etapu stają się sekcjami na stronie etapu.
- **Pliki `.md`** są zamieniane na strony (tabele, kod, spis treści, linki między plikami `.md` działają).
  Opcjonalny nagłówek:
  ```markdown
  ---
  title: Tytuł
  date: 2024-05-01
  tags: [wersja, notatki]
  opis: Krótki opis na kartę.
  ---
  ```
- **Obrazy** trafiają do galerii etapu.
- **Katalog z `index.html`** (np. cała stara strona z CSS i obrazkami) jest pokazywany jako jeden wpis
  „Strona HTML” i działa dokładnie tak jak wcześniej — struktura plików jest kopiowana 1:1.
- **PDF, ZIP, wideo, inne pliki** — kopiowane bez zmian i podlinkowane.
- **Data** materiału: z nagłówka `date:`, z prefiksu nazwy (`2024-05-01-notatki.md`)
  albo z daty ostatniego commita.

Na stronie: strona główna z etapami, **oś czasu**, strona każdego etapu, spis **wszystkiego**
z filtrami oraz wyszukiwarka (klawisz `/`). Jasny i ciemny motyw.

## Uruchomienie Pages (jednorazowo)

1. **Settings → Pages → Build and deployment → Source: „GitHub Actions”.**
2. Wypchnij zmiany na `main` — workflow `.github/workflows/pages.yml` zbuduje i opublikuje stronę
   pod adresem `https://<użytkownik>.github.io/FoE-MG/`.
   Można też uruchomić go ręcznie: zakładka **Actions → Strona (GitHub Pages) → Run workflow**.

## Podgląd lokalnie

```bash
pip install -r tools/requirements.txt
python tools/build.py
python -m http.server -d _site 8000   # http://localhost:8000
```

## Struktura repozytorium

| Ścieżka | Co to jest |
|---|---|
| `content/` | **Twoje materiały** — tylko tu trzeba coś dodawać |
| `tools/build.py` | generator strony |
| `theme/` | wygląd (CSS) i skrypty (wyszukiwarka, filtry, motyw) |
| `.github/workflows/pages.yml` | automatyczna publikacja na GitHub Pages |
