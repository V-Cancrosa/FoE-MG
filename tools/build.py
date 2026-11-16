#!/usr/bin/env python3
"""
Generator strony FoE-MG dla GitHub Pages.

Czyta wszystko z katalogu `content/` i składa z tego jedną spójną stronę w `_site/`:
  * każdy katalog najwyższego poziomu w content/ = jeden etap (np. 01-stare, 02-pomiedzy, 03-nowe),
  * pliki .md są renderowane do HTML (z nawigacją, w szablonie strony),
  * wszystkie inne pliki (obrazy, PDF, HTML, ZIP, ...) są kopiowane 1:1 i podlinkowane,
  * powstaje strona główna z osią etapów, strona każdego etapu, pełny spis z wyszukiwarką.

Użycie:  python tools/build.py [--content content] [--out _site]
Zależność: pip install markdown
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

try:
    import markdown as md_lib
except ImportError:  # pragma: no cover
    sys.exit("Brak biblioteki 'markdown'. Zainstaluj: pip install markdown")

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "theme"

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp"}
DOC_EXT = {".md", ".markdown"}
HTML_EXT = {".html", ".htm"}
PDF_EXT = {".pdf"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}
AUDIO_EXT = {".mp3", ".ogg", ".wav", ".m4a"}
TEXT_EXT = {".txt", ".csv", ".json", ".xml", ".yml", ".yaml", ".log", ".ini", ".js", ".css", ".py"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz"}

TYPE_LABEL = {
    "doc": "Dokument",
    "html": "Strona HTML",
    "image": "Obraz",
    "pdf": "PDF",
    "video": "Wideo",
    "audio": "Audio",
    "text": "Plik tekstowy",
    "archive": "Archiwum",
    "other": "Plik",
}
TYPE_ICON = {
    "doc": "📄", "html": "🌐", "image": "🖼️", "pdf": "📕", "video": "🎬",
    "audio": "🎵", "text": "📝", "archive": "📦", "other": "📎",
}

SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitkeep"}
META_FILES = {"_info.md", "_index.md", "_site.json"}


# --------------------------------------------------------------------------- utils

def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def url(path: str) -> str:
    """Zakoduj ścieżkę względną (polskie znaki, spacje) do użycia w href/src."""
    return quote(path, safe="/#?=&.-_~%")


PREFIX_RE = re.compile(r"^\d+[\s._-]+")
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[\s._-]*")


def pretty_name(name: str) -> str:
    stem = name
    m = DATE_PREFIX_RE.match(stem)
    if m:
        stem = stem[m.end():] or m.group(1)
    else:
        stem = PREFIX_RE.sub("", stem) or stem
    stem = re.sub(r"[_-]+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else name


def slugify(s: str) -> str:
    table = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    s = s.translate(table).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "x"


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Prosty front matter: linie `klucz: wartość` między `---`."""
    meta: dict = {}
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---"):
        return meta, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return meta, text
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() in ("---", "..."):
            body = "\n".join(lines[i + 1:])
            return meta, body
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().strip('"').strip("'")
            if v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
            meta[k.strip().lower()] = v
    return {}, text  # brak zamknięcia — traktuj jako zwykły tekst


def as_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        return v
    return [x.strip() for x in str(v).split(",") if x.strip()]


def git_dates(content_dir: Path) -> dict[str, str]:
    """Data ostatniego commita dla każdego pliku (jeśli jest historia git)."""
    out: dict[str, str] = {}
    try:
        res = subprocess.run(
            ["git", "log", "--format=@%cs", "--name-only", "--", str(content_dir)],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
    except Exception:
        return out
    current = None
    for line in res.stdout.splitlines():
        if line.startswith("@"):
            current = line[1:]
        elif line.strip() and current:
            p = (ROOT / line.strip()).resolve()
            out.setdefault(str(p), current)  # pierwsze wystąpienie = najnowszy commit
    return out


def file_type(ext: str) -> str:
    ext = ext.lower()
    if ext in DOC_EXT: return "doc"
    if ext in HTML_EXT: return "html"
    if ext in IMAGE_EXT: return "image"
    if ext in PDF_EXT: return "pdf"
    if ext in VIDEO_EXT: return "video"
    if ext in AUDIO_EXT: return "audio"
    if ext in TEXT_EXT: return "text"
    if ext in ARCHIVE_EXT: return "archive"
    return "other"


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def summarize(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


# --------------------------------------------------------------------------- model

@dataclass
class Item:
    rel: str            # ścieżka względem content/ (z /)
    src: Path
    collection: str     # slug etapu
    folder: str         # podkatalog wewnątrz etapu ("" = główny)
    kind: str
    title: str
    href: str           # ścieżka wynikowa względem korzenia strony
    date: str = ""
    summary: str = ""
    tags: list = field(default_factory=list)
    size: int = 0
    order: str = ""
    body_html: str = ""
    toc_html: str = ""


@dataclass
class Collection:
    slug: str
    dirname: str
    title: str
    description_html: str = ""
    summary: str = ""
    period: str = ""
    order: str = ""
    items: list = field(default_factory=list)


# --------------------------------------------------------------------------- build

class Builder:
    def __init__(self, content: Path, out: Path):
        self.content = content
        self.out = out
        self.site = {
            "title": "FoE-MG",
            "subtitle": "Wszystko w jednym miejscu — stare, nowe i to, co pomiędzy.",
            "lang": "pl",
            "footer": "",
        }
        cfg = content / "_site.json"
        if cfg.exists():
            try:
                self.site.update(json.loads(cfg.read_text(encoding="utf-8")))
            except json.JSONDecodeError as e:
                print(f"⚠ _site.json: błąd JSON ({e}) — używam domyślnych ustawień")
        self.collections: dict[str, Collection] = {}
        self.items: list[Item] = []
        self.dates = git_dates(content)
        self.md_paths: dict[str, str] = {}  # rel .md -> href .html

    # ---- markdown
    def md(self, text: str) -> tuple[str, str]:
        conv = md_lib.Markdown(
            extensions=["extra", "toc", "sane_lists", "smarty"],
            extension_configs={"toc": {"permalink": "#", "permalink_class": "anchor", "toc_depth": "2-4"}},
            output_format="html",
        )
        body = conv.convert(text)
        return body, getattr(conv, "toc", "")

    def rewrite_links(self, body: str, item_rel: str) -> str:
        """Linki do .md w tekście → odpowiadające im wygenerowane strony .html."""
        base = Path(item_rel).parent

        def repl(m):
            attr, q, target = m.group(1), m.group(2), m.group(3)
            if re.match(r"^[a-z]+:|^#|^/", target):
                return m.group(0)
            path, _, frag = target.partition("#")
            from urllib.parse import unquote
            norm = os.path.normpath(str(base / unquote(path))).replace("\\", "/")
            if norm in self.md_paths:
                new = os.path.relpath("k/" + self.md_paths[norm], "k/" + str(base)).replace("\\", "/")
                new = url(new) + (("#" + frag) if frag else "")
                return f'{attr}={q}{new}{q}'
            return m.group(0)

        return re.sub(r'(href|src)=(["\'])([^"\']+)\2', repl, body)

    # ---- scan
    def scan(self):
        if not self.content.exists():
            sys.exit(f"Brak katalogu {self.content}")
        for d in sorted(p for p in self.content.iterdir() if p.is_dir() and not p.name.startswith(".")):
            self.add_collection(d)
        loose = [p for p in self.content.iterdir()
                 if p.is_file() and p.name not in META_FILES and p.name not in SKIP_NAMES
                 and not p.name.startswith(".")]
        if loose:
            col = Collection(slug="inne", dirname="", title="Inne", order="zzz")
            self.collections[col.slug] = col
            for f in sorted(loose):
                self.add_file(col, f)

        # pass 2: render markdown (po zebraniu wszystkich ścieżek, żeby działały linki między plikami)
        for it in self.items:
            if it.kind == "doc":
                raw = it.src.read_text(encoding="utf-8", errors="replace")
                _, body = parse_front_matter(raw)
                html_body, toc = self.md(body)
                it.body_html = self.rewrite_links(html_body, it.rel)
                it.toc_html = toc if toc.count("<li") >= 2 else ""

    def add_collection(self, d: Path):
        title, desc_html, summary, period = pretty_name(d.name), "", "", ""
        info = d / "_info.md"
        if info.exists():
            meta, body = parse_front_matter(info.read_text(encoding="utf-8", errors="replace"))
            title = meta.get("title") or meta.get("tytul") or meta.get("tytuł") or title
            period = meta.get("okres") or meta.get("period") or ""
            body = body.strip()
            m = re.match(r"^#\s+(.+)\n?", body)
            if m and not (meta.get("title") or meta.get("tytul") or meta.get("tytuł")):
                title = m.group(1).strip()
            if m:
                body = body[m.end():].strip()
            if body:
                desc_html, _ = self.md(body)
                summary = summarize(strip_tags(desc_html), 220)
            summary = meta.get("opis") or meta.get("description") or summary
        slug = slugify(d.name)
        base, n = slug, 2
        while slug in self.collections:
            slug, n = f"{base}-{n}", n + 1
        col = Collection(slug=slug, dirname=d.name, title=title, description_html=desc_html,
                         summary=summary, period=period, order=d.name)
        self.collections[slug] = col
        # katalog z index.html = cała strona/aplikacja: pokazujemy jeden wpis, resztę tylko kopiujemy
        site_dirs = sorted({p.parent for p in d.rglob("index.htm*") if p.name.lower() in ("index.html", "index.htm")},
                           key=lambda p: len(p.parts))
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.name in SKIP_NAMES:
                continue
            relparts = f.relative_to(d).parts
            if any(part.startswith(".") for part in relparts):
                continue
            owner = next((s for s in site_dirs if f.parent == s or s in f.parents), None)
            if owner is not None and not (f.parent == owner and f.name.lower() in ("index.html", "index.htm")):
                continue
            if f.name == "_info.md" and f.parent == d:
                continue
            self.add_file(col, f)

    def add_file(self, col: Collection, f: Path):
        rel = f.relative_to(self.content).as_posix()
        ext = f.suffix.lower()
        kind = file_type(ext)
        inner = Path(rel).parts[1:-1] if col.dirname else ()
        is_site = f.name.lower() in ("index.html", "index.htm")
        if is_site and inner:
            inner = inner[:-1]  # cała strona trafia do sekcji katalogu nadrzędnego
        folder = "/".join(inner)
        date, title, summary, tags = "", pretty_name(f.stem), "", []
        if is_site:
            title = pretty_name(f.parent.name)
            summary = f"Strona HTML: {f.parent.relative_to(self.content).as_posix()}/"
        m = DATE_PREFIX_RE.match(f.name)
        if m:
            date = m.group(1)

        if kind == "doc":
            raw = f.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_front_matter(raw)
            h = re.search(r"^#\s+(.+)$", body, re.M)
            title = meta.get("title") or meta.get("tytul") or meta.get("tytuł") or (h.group(1).strip() if h else title)
            date = meta.get("date") or meta.get("data") or date
            tags = as_list(meta.get("tags") or meta.get("tagi"))
            summary = meta.get("opis") or meta.get("description") or ""
            if not summary:
                paras = [p for p in re.split(r"\n\s*\n", body)
                         if p.strip() and not p.lstrip().startswith(("#", "!", "|", "```", "<", "-", "*", ">"))]
                if paras:
                    summary = summarize(re.sub(r"[*_`]", "", re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", paras[0])))
            out_rel = rel[: -len(f.suffix)] + ".html"
            if (self.content / out_rel).exists():
                out_rel = rel + ".html"
            self.md_paths[rel] = out_rel
            href = "k/" + out_rel
        else:
            href = "k/" + rel
            if kind == "html":
                try:
                    t = re.search(r"<title[^>]*>(.*?)</title>", f.read_text(encoding="utf-8", errors="replace"),
                                  re.I | re.S)
                    if t and t.group(1).strip():
                        title = html.unescape(t.group(1).strip())
                except OSError:
                    pass

        if not date:
            date = self.dates.get(str(f.resolve()), "")
        if not date:
            date = dt.date.fromtimestamp(f.stat().st_mtime).isoformat()

        it = Item(rel=rel, src=f, collection=col.slug, folder=folder, kind=kind, title=title,
                  href=href, date=str(date), summary=summary, tags=tags, size=f.stat().st_size,
                  order=rel.lower())
        col.items.append(it)
        self.items.append(it)

    # ---- render helpers
    def nav(self, root: str, active: str) -> str:
        links = [("index.html", "Start", "home"), ("os-czasu.html", "Oś czasu", "timeline"),
                 ("wszystko.html", "Wszystko", "all")]
        cols = self.ordered_collections()
        col_links = "".join(
            f'<a href="{root}e/{c.slug}/index.html" class="{"active" if active == "c:" + c.slug else ""}">{esc(c.title)}</a>'
            for c in cols)
        main = "".join(f'<a href="{root}{h}" class="{"active" if active == k else ""}">{t}</a>' for h, t, k in links)
        return f"""
<header class="topbar">
  <a class="brand" href="{root}index.html"><span class="logo" aria-hidden="true">◆</span>{esc(self.site['title'])}</a>
  <button class="menu-btn" aria-label="Menu" aria-expanded="false" data-menu>☰</button>
  <nav class="mainnav" data-nav>
    {main}
    <span class="sep" aria-hidden="true"></span>
    {col_links}
  </nav>
  <div class="tools">
    <button class="icon-btn" data-search-open aria-label="Szukaj" title="Szukaj (/)"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg></button>
    <button class="icon-btn" data-theme-toggle aria-label="Zmień motyw" title="Jasny / ciemny"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/></svg></button>
  </div>
</header>"""

    def page(self, root: str, title: str, body: str, active: str = "", description: str = "") -> str:
        full_title = title if title == self.site["title"] else f"{title} · {self.site['title']}"
        footer = self.site.get("footer") or ""
        built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return f"""<!doctype html>
<html lang="{esc(self.site.get('lang', 'pl'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description or self.site['subtitle'])}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>◆</text></svg>">
<link rel="stylesheet" href="{root}assets/style.css">
<script>try{{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
<body data-root="{root}">
{self.nav(root, active)}
<main class="wrap">
{body}
</main>
<footer class="foot">
  <div class="wrap">
    <span>{esc(self.site['title'])}</span>
    {f'<span>{esc(footer)}</span>' if footer else ''}
    <span class="muted">Zbudowano {built} · {len(self.items)} materiałów</span>
  </div>
</footer>
<div class="search-modal" data-search-modal hidden>
  <div class="search-box" role="dialog" aria-label="Wyszukiwarka">
    <input type="search" placeholder="Szukaj we wszystkich materiałach…" data-search-input autocomplete="off">
    <ul class="search-results" data-search-results></ul>
    <p class="search-hint muted">Enter — otwórz · Esc — zamknij</p>
  </div>
</div>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""

    def ordered_collections(self) -> list[Collection]:
        return sorted(self.collections.values(), key=lambda c: c.order)

    def item_card(self, it: Item, root: str, show_col: bool = False) -> str:
        col = self.collections[it.collection]
        thumb = ""
        if it.kind == "image":
            thumb = f'<img class="thumb" src="{root}{url(it.href)}" alt="" loading="lazy">'
        meta = [f'<span class="badge t-{it.kind}">{TYPE_ICON[it.kind]} {TYPE_LABEL[it.kind]}</span>']
        if show_col:
            meta.append(f'<span class="badge col">{esc(col.title)}</span>')
        if it.date:
            meta.append(f'<time datetime="{esc(it.date)}">{esc(it.date)}</time>')
        if it.kind != "doc":
            meta.append(f'<span class="muted">{human_size(it.size)}</span>')
        tags = "".join(f'<span class="tag">#{esc(t)}</span>' for t in it.tags)
        target = ' target="_blank" rel="noopener"' if it.kind in ("pdf", "html", "archive", "other", "video", "audio", "text") else ""
        return f"""<a class="card kind-{it.kind}" href="{root}{url(it.href)}"{target}
   data-kind="{it.kind}" data-col="{it.collection}" data-text="{esc((it.title + ' ' + it.summary + ' ' + ' '.join(it.tags) + ' ' + it.rel).lower())}">
  {thumb}
  <div class="card-body">
    <h3>{esc(it.title)}</h3>
    {f'<p>{esc(it.summary)}</p>' if it.summary else ''}
    <div class="meta">{''.join(meta)}{tags}</div>
  </div>
</a>"""

    # ---- pages
    def render_home(self):
        root = ""
        intro_html = ""
        idx = self.content / "_index.md"
        if idx.exists():
            _, body = parse_front_matter(idx.read_text(encoding="utf-8", errors="replace"))
            intro_html, _ = self.md(body)
        cols = self.ordered_collections()
        steps = []
        for i, c in enumerate(cols, 1):
            kinds = {}
            for it in c.items:
                kinds[it.kind] = kinds.get(it.kind, 0) + 1
            counts = " · ".join(f"{TYPE_ICON[k]} {n}" for k, n in sorted(kinds.items(), key=lambda x: -x[1]))
            steps.append(f"""
<li class="stage">
  <a href="e/{c.slug}/index.html">
    <span class="stage-no">{i:02d}</span>
    <span class="stage-title">{esc(c.title)}</span>
    {f'<span class="stage-period">{esc(c.period)}</span>' if c.period else ''}
    {f'<span class="stage-desc">{esc(c.summary)}</span>' if c.summary else ''}
    <span class="stage-count">{len(c.items)} {plural(len(c.items))}{(' · ' + counts) if counts else ''}</span>
  </a>
</li>""")
        recent = sorted(self.items, key=lambda x: (x.date, x.rel), reverse=True)[:8]
        recent_html = "".join(self.item_card(it, root, show_col=True) for it in recent)
        body = f"""
<section class="hero">
  <h1>{esc(self.site['title'])}</h1>
  <p class="lead">{esc(self.site['subtitle'])}</p>
  <div class="hero-actions">
    <a class="btn primary" href="os-czasu.html">Oś czasu</a>
    <a class="btn" href="wszystko.html">Przeglądaj wszystko</a>
  </div>
</section>
{f'<section class="prose intro">{intro_html}</section>' if intro_html.strip() else ''}
<section>
  <h2 class="section-title">Etapy</h2>
  <ol class="stages">{''.join(steps) or '<li class="empty">Brak materiałów — dodaj pliki do katalogu <code>content/</code>.</li>'}</ol>
</section>
{f'<section><h2 class="section-title">Ostatnio zmienione</h2><div class="grid">{recent_html}</div></section>' if recent else ''}
"""
        self.write("index.html", self.page(root, self.site["title"], body, "home"))

    def render_collection(self, c: Collection):
        root = "../../"
        groups: dict[str, list[Item]] = {}
        for it in sorted(c.items, key=lambda x: x.order):
            groups.setdefault(it.folder, []).append(it)
        cols = self.ordered_collections()
        i = cols.index(c)
        prev_c = cols[i - 1] if i > 0 else None
        next_c = cols[i + 1] if i + 1 < len(cols) else None
        sections = []
        for folder in sorted(groups, key=lambda f: (f != "", f.lower())):
            items = groups[folder]
            imgs = [x for x in items if x.kind == "image"]
            rest = [x for x in items if x.kind != "image"]
            head = ""
            if folder:
                crumbs = " / ".join(pretty_name(p) for p in folder.split("/"))
                head = f'<h2 class="section-title" id="{slugify(folder)}">{esc(crumbs)}</h2>'
            gallery = ""
            if imgs:
                gallery = '<div class="gallery">' + "".join(
                    f'<a href="{root}{url(x.href)}" data-lightbox title="{esc(x.title)}"><img src="{root}{url(x.href)}" alt="{esc(x.title)}" loading="lazy"></a>'
                    for x in imgs) + "</div>"
            cards = '<div class="grid">' + "".join(self.item_card(x, root) for x in rest) + "</div>" if rest else ""
            sections.append(f"<section>{head}{cards}{gallery}</section>")
        pager = f"""<nav class="pager">
  {f'<a href="../{prev_c.slug}/index.html" class="prev">← {esc(prev_c.title)}</a>' if prev_c else '<span></span>'}
  {f'<a href="../{next_c.slug}/index.html" class="next">{esc(next_c.title)} →</a>' if next_c else '<span></span>'}
</nav>"""
        body = f"""
<nav class="crumbs"><a href="{root}index.html">Start</a> / <span>{esc(c.title)}</span></nav>
<header class="page-head">
  <span class="eyebrow">Etap {i + 1:02d} z {len(cols):02d}{(' · ' + esc(c.period)) if c.period else ''}</span>
  <h1>{esc(c.title)}</h1>
  <p class="muted">{len(c.items)} {plural(len(c.items))}</p>
</header>
{f'<div class="prose">{c.description_html}</div>' if c.description_html else ''}
{''.join(sections) if c.items else '<p class="empty">Ten etap jest jeszcze pusty.</p>'}
{pager}
"""
        self.write(f"e/{c.slug}/index.html", self.page(root, c.title, body, "c:" + c.slug, c.summary))

    def render_doc(self, it: Item):
        depth = it.href.count("/")
        root = "../" * depth
        c = self.collections[it.collection]
        siblings = sorted([x for x in c.items if x.kind == "doc"], key=lambda x: x.order)
        i = siblings.index(it)
        prev_d = siblings[i - 1] if i > 0 else None
        next_d = siblings[i + 1] if i + 1 < len(siblings) else None
        crumbs = [f'<a href="{root}index.html">Start</a>', f'<a href="{root}e/{c.slug}/index.html">{esc(c.title)}</a>']
        if it.folder:
            crumbs.append(f'<a href="{root}e/{c.slug}/index.html#{slugify(it.folder)}">{esc(" / ".join(pretty_name(p) for p in it.folder.split("/")))}</a>')
        tags = "".join(f'<span class="tag">#{esc(t)}</span>' for t in it.tags)
        body_html = it.body_html
        # usuń zdublowany nagłówek H1, jeśli jest identyczny z tytułem
        body_html = re.sub(r'^\s*<h1[^>]*>' + re.escape(esc(it.title)) + r'(?:<a[^>]*>#</a>)?</h1>', "", body_html, count=1)
        source = os.path.relpath("k/" + it.rel, os.path.dirname(it.href)).replace("\\", "/")
        body = f"""
<nav class="crumbs">{' / '.join(crumbs)}</nav>
<div class="doc-layout{' has-toc' if it.toc_html else ''}">
  <article class="prose doc">
    <header class="page-head">
      <h1>{esc(it.title)}</h1>
      <div class="meta">{f'<time datetime="{esc(it.date)}">{esc(it.date)}</time>' if it.date else ''}{tags}
        <a class="muted src" href="{url(source)}">źródło .md</a></div>
    </header>
    {body_html}
  </article>
  {f'<aside class="toc"><strong>Spis treści</strong>{it.toc_html}</aside>' if it.toc_html else ''}
</div>
<nav class="pager">
  {f'<a href="{root}{url(prev_d.href)}" class="prev">← {esc(prev_d.title)}</a>' if prev_d else '<span></span>'}
  {f'<a href="{root}{url(next_d.href)}" class="next">{esc(next_d.title)} →</a>' if next_d else '<span></span>'}
</nav>
"""
        self.write(it.href, self.page(root, it.title, body, "c:" + c.slug, it.summary))

    def render_all(self):
        root = ""
        kinds = sorted({it.kind for it in self.items}, key=lambda k: list(TYPE_LABEL).index(k))
        cols = self.ordered_collections()
        filters_col = "".join(f'<option value="{c.slug}">{esc(c.title)}</option>' for c in cols)
        filters_kind = "".join(f'<option value="{k}">{TYPE_ICON[k]} {TYPE_LABEL[k]}</option>' for k in kinds)
        cards = "".join(self.item_card(it, root, show_col=True)
                        for it in sorted(self.items, key=lambda x: (cols.index(self.collections[x.collection]), x.order)))
        body = f"""
<header class="page-head">
  <h1>Wszystkie materiały</h1>
  <p class="muted"><span data-count>{len(self.items)}</span> z {len(self.items)}</p>
</header>
<div class="filters" data-filters>
  <input type="search" placeholder="Filtruj po nazwie, opisie, tagu…" data-filter-text>
  <select data-filter-col><option value="">Wszystkie etapy</option>{filters_col}</select>
  <select data-filter-kind><option value="">Wszystkie typy</option>{filters_kind}</select>
</div>
<div class="grid" data-filter-grid>{cards}</div>
<p class="empty" data-filter-empty hidden>Nic nie pasuje do filtrów.</p>
"""
        self.write("wszystko.html", self.page(root, "Wszystko", body, "all"))

    def render_timeline(self):
        root = ""
        cols = self.ordered_collections()
        blocks = []
        for i, c in enumerate(cols, 1):
            items = sorted(c.items, key=lambda x: (x.date, x.order))
            entries = "".join(f"""
<li class="tl-item">
  <time>{esc(it.date)}</time>
  <a href="{url(it.href)}"{' target="_blank" rel="noopener"' if it.kind not in ('doc', 'image') else ''}>{TYPE_ICON[it.kind]} {esc(it.title)}</a>
  {f'<span class="muted">{esc(it.folder)}</span>' if it.folder else ''}
</li>""" for it in items)
            dates = [it.date for it in items if it.date]
            span = f"{min(dates)} → {max(dates)}" if dates else ""
            blocks.append(f"""
<section class="tl-stage">
  <div class="tl-marker"><span>{i:02d}</span></div>
  <div class="tl-content">
    <h2><a href="e/{c.slug}/index.html">{esc(c.title)}</a></h2>
    <p class="muted">{esc(c.period) or esc(span)}</p>
    {f'<p>{esc(c.summary)}</p>' if c.summary else ''}
    <ol class="tl-list">{entries}</ol>
  </div>
</section>""")
        body = f"""
<header class="page-head">
  <h1>Oś czasu</h1>
  <p class="muted">Od najstarszego etapu do najnowszego — wszystko po kolei.</p>
</header>
<div class="timeline">{''.join(blocks) or '<p class="empty">Brak materiałów.</p>'}</div>
"""
        self.write("os-czasu.html", self.page(root, "Oś czasu", body, "timeline"))

    def render_404(self):
        body = """<section class="hero"><h1>404</h1><p class="lead">Nie ma takiej strony.</p>
<div class="hero-actions"><a class="btn primary" data-home href="index.html">Wróć na start</a></div></section>
<script>document.querySelectorAll('[data-home]').forEach(a=>{var p=location.pathname.split('/').filter(Boolean);if(location.hostname.endsWith('github.io')&&p.length)a.href='/'+p[0]+'/';});</script>"""
        html_out = self.page("", "Nie znaleziono", body)
        # w 404 ścieżki względne nie działają — ustaw base na katalog repozytorium (project pages)
        html_out = html_out.replace("<head>", """<head>
<script>(function(){var p=location.pathname.split('/').filter(Boolean);var b=(location.hostname.endsWith('github.io')&&p.length)?'/'+p[0]+'/':'/';document.write('<base href="'+b+'">');})();</script>""", 1)
        self.write("404.html", html_out)

    def write_search_index(self):
        data = []
        for it in self.items:
            text = it.summary
            if it.kind == "doc":
                clean = re.sub(r'<a class="anchor"[^>]*>#</a>', "", it.body_html)
                clean = re.sub(r"<h1[^>]*>.*?</h1>", "", clean, count=1, flags=re.S)
                text = summarize(strip_tags(clean), 600)
            data.append({
                "t": it.title, "h": it.href, "k": it.kind, "c": self.collections[it.collection].title,
                "d": it.date, "s": text, "g": it.tags, "p": it.rel,
            })
        self.write("search.json", json.dumps(data, ensure_ascii=False))

    # ---- io
    def write(self, rel: str, text: str):
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def run(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self.scan()
        # kopia wszystkich materiałów 1:1 (zachowuje względne linki w starych stronach HTML)
        shutil.copytree(self.content, self.out / "k", ignore=shutil.ignore_patterns(".*", *SKIP_NAMES),
                        dirs_exist_ok=True)
        shutil.copytree(THEME, self.out / "assets", dirs_exist_ok=True)
        (self.out / ".nojekyll").write_text("")
        self.render_home()
        self.render_timeline()
        self.render_all()
        for c in self.collections.values():
            self.render_collection(c)
        for it in self.items:
            if it.kind == "doc":
                self.render_doc(it)
        self.render_404()
        self.write_search_index()
        print(f"✔ Zbudowano {self.out} — {len(self.collections)} etapów, {len(self.items)} materiałów")
        for c in self.ordered_collections():
            print(f"   • {c.title}: {len(c.items)}")


def plural(n: int) -> str:
    if n == 1:
        return "materiał"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "materiały"
    return "materiałów"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--content", default=str(ROOT / "content"))
    ap.add_argument("--out", default=str(ROOT / "_site"))
    a = ap.parse_args()
    Builder(Path(a.content).resolve(), Path(a.out).resolve()).run()


if __name__ == "__main__":
    main()
