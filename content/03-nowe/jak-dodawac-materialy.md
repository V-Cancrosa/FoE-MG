---
title: Jak dodawać materiały
tags: [instrukcja]
---

# Jak dodawać materiały

Wszystko, co trafi do katalogu `content/` w repozytorium, pojawi się automatycznie na stronie
po każdym pushu na gałąź `main`.

## Etapy

Każdy katalog w `content/` to jeden **etap**. Kolejność ustalają numery na początku nazwy:

| Katalog | Etap |
|---|---|
| `content/01-stare/` | Stare |
| `content/02-pomiedzy/` | Pomiędzy |
| `content/03-nowe/` | Nowe |

Możesz dodać kolejne (`04-…`), zmienić nazwy albo wstawić etap pośredni, np. `02a-…`.

## Pliki

- **`.md`** — zamieniane na ładne strony (nagłówki, tabele, spis treści).
- **obrazy** — trafiają do galerii etapu.
- **`.html`, PDF, ZIP, wideo i inne** — kopiowane bez zmian i podlinkowane.
  Całe stare strony HTML (z obrazkami i CSS obok) działają, bo struktura katalogów jest zachowana.

Podkatalogi wewnątrz etapu stają się sekcjami na jego stronie.

## Opis etapu

Plik `_info.md` w katalogu etapu ustawia tytuł, okres i opis.

## Ten plik

Możesz go usunąć, gdy wrzucisz już swoje materiały.
