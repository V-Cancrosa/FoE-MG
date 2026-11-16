# Stajnia 97 „Gardens” — materiały kampanii Fallout: Equestria

Strona: **https://v-cancrosa.github.io/FoE-MG/**

Wszystkie materiały kampanii (świat, materiały dla graczy, postacie, mapy, notatki MG) złożone
w jedną stronę. Strona buduje się sama po każdym pushu.

## Jak dodawać materiały

**Najprościej:** wrzuć pliki przez „Add files → Upload files” gdziekolwiek w repozytorium.
Pliki wrzucone luzem do katalogu głównego automat przeniesie do
`content/99-do-posortowania/` i od razu pokaże na stronie w dziale „Do posortowania”.
Potem można je przenieść do właściwego działu.

**Porządnie:** wrzucaj od razu do właściwego katalogu w `content/`:

```
content/
├── _site.json            ← tytuł, podtytuł, grafika nagłówka, herb
├── _index.md             ← tekst powitalny na stronie głównej
├── 01-swiat/             ← Świat i Stajnia 97
├── 02-dla-graczy/        ← wybór rasy, ściągi, materiały fabularne, zaproszenia
├── 03-postacie/          ← jeden podkatalog na postać
├── 04-mapy/
├── 05-dla-mg/            ← spoilery (strona ostrzega graczy przed wejściem)
└── 06-galeria/
```

- **Dział** = katalog w `content/`; kolejność wg numeru w nazwie. **Podkatalog** = sekcja działu.
- `_info.md` w dziale: tytuł, podpis, opis; `spoiler: tak` włącza ostrzeżenie „tylko dla MG”
  i ukrywa dział na osi czasu, w „Najnowszych” i w wyszukiwarce.
- `_opisy.json` w dziale: ładne tytuły i opisy plików (np. PDF-ów), opcjonalnie daty.
- **`.md`** → pełna strona ze spisem treści. **Obrazy** → galeria z miniaturami.
- **Ten sam plik w kilku formatach** (`X.html` + `X.pdf`, `X.webp` + `X.svg`) → jeden wpis z przyciskami formatów.
- **Starsze wersje** trzymaj w podkatalogu „starsze wersje” — będą pokazane na końcu działu.
- **Data** materiału: z nagłówka dokumentu (np. „Oct 5, 2026”), metadanych PDF/DOCX/ZIP,
  albo z chwili dodania do repozytorium. Na tej podstawie powstaje **oś czasu**.

## Jak to działa

- Pages: *Settings → Pages → Deploy from a branch*, katalog `/ (root)`.
- Workflow `.github/workflows/build.yml` po pushu uruchamia `tools/build.py` i commituje
  wygenerowane pliki (`index.html`, `e/`, `p/`, `t/`, `assets/`, …) na tę samą gałąź.
  Tych plików nie edytuj ręcznie — zostaną nadpisane.
- `theme/` — wygląd (CSS) i skrypty (wyszukiwarka `/`, filtry, motyw, ostrzeżenie MG).

> ⚠️ Strona i repozytorium są publiczne. Ostrzeżenie w dziale „Dla MG” tylko odstrasza —
> nie chroni przed kimś, kto naprawdę chce zajrzeć.

## Podgląd lokalnie

```bash
pip install -r tools/requirements.txt
python tools/build.py
python -m http.server 8000   # http://localhost:8000
```

## Wydanie zbiorcze „Jednostrzał i sesje zero” (PDF dla MG)

Źródła są w `wydanie/`: rozdziały w `wydanie/rozdzialy/*.md` (Markdown z ramkami `::: read`, `::: note`,
`::: ledger`, `::: secret`), styl w `wydanie/wydanie.css`, fonty w `wydanie/fonts/`.
Część rozdziałów wczytuje pliki z `content/` na bieżąco (sesja zero dwellera, przewodnik, ściąga, handouty),
więc po ich zmianie wystarczy przebudować:

```bash
pip install markdown weasyprint==70.0 python-docx Pillow
python wydanie/build.py          # → content/05-dla-mg/FoE_Jednostrzal_i_sesje_zero_MG.pdf + .html
python tools/build.py            # odświeża stronę
```
