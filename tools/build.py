#!/usr/bin/env python3
"""
Generator strony kampanii dla GitHub Pages.

Czyta wszystko z katalogu `content/` i składa z tego jedną spójną stronę:
  * każdy katalog najwyższego poziomu w content/ = jeden dział (kolejność wg numeru w nazwie),
  * podkatalogi = sekcje działu,
  * pliki .md są renderowane do stron HTML,
  * obrazy trafiają do galerii (z miniaturami, jeśli jest Pillow),
  * pliki o tej samej nazwie (np. X.html + X.pdf, X.svg + X.webp) są łączone w jeden wpis,
  * pozostałe pliki (PDF, HTML, DOCX, ZIP, ...) są podlinkowane bez zmian.

Domyślnie strona jest generowana w katalogu głównym repozytorium (tryb „Deploy from a branch”),
a materiały są linkowane bezpośrednio z content/. Opcja --out <katalog> buduje osobną kopię.

Użycie:  python tools/build.py [--out _site]
Zależności: markdown (wymagana), Pillow (opcjonalnie — miniatury obrazów)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

try:
    import markdown as md_lib
except ImportError:  # pragma: no cover
    sys.exit("Brak biblioteki 'markdown'. Zainstaluj: pip install markdown")
try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "theme"

# pliki/katalogi generowane w katalogu docelowym (tylko te są czyszczone przy przebudowie)
HOME = "biblioteka.html"  # spis materiałów; index.html to interaktywne wydanie MG
GENERATED = ["index.html", "biblioteka.html", "os-czasu.html", "wszystko.html", "404.html", "search.json",
             "e", "p", "t", "assets", ".nojekyll"]

KINDS = {
    "doc": ({".md", ".markdown"}, "Dokument", "📄"),
    "html": ({".html", ".htm"}, "Strona", "🌐"),
    "image": ({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp"}, "Obraz", "🖼️"),
    "pdf": ({".pdf"}, "PDF", "📕"),
    "word": ({".docx", ".doc", ".odt", ".rtf"}, "Word", "📘"),
    "video": ({".mp4", ".webm", ".mov"}, "Wideo", "🎬"),
    "audio": ({".mp3", ".ogg", ".wav", ".m4a"}, "Audio", "🎵"),
    "text": ({".txt", ".csv", ".json", ".xml", ".yml", ".yaml", ".log"}, "Plik danych", "📝"),
    "archive": ({".zip", ".rar", ".7z", ".tar", ".gz"}, "Archiwum", "📦"),
    "other": (set(), "Plik", "📎"),
}
TYPE_LABEL = {k: v[1] for k, v in KINDS.items()}
TYPE_ICON = {k: v[2] for k, v in KINDS.items()}
PRIMARY_ORDER = ["doc", "html", "image", "pdf", "word", "video", "audio", "text", "archive", "other"]
RASTER = {".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif"}

SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitkeep"}
META_FILES = {"_info.md", "_index.md", "_site.json", "_opisy.json"}
MONTHS_EN = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTHS_PL = ["", "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień",
             "wrzesień", "październik", "listopad", "grudzień"]


# --------------------------------------------------------------------------- utils

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def url(path: str) -> str:
    """Zakoduj ścieżkę (polskie znaki, spacje, nawiasy) do użycia w href/src."""
    return quote(path, safe="/#=&.-_~%")


PREFIX_RE = re.compile(r"^\d+[a-z]?[\s._-]+")
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[\s._-]*")


def pretty_name(name: str) -> str:
    stem = name
    m = DATE_PREFIX_RE.match(stem)
    if m:
        stem = stem[m.end():] or m.group(1)
    else:
        stem = PREFIX_RE.sub("", stem) or stem
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"(?<=\w)-(?=\w)", " ", stem) if " " not in stem else stem
    stem = re.sub(r"\s+", " ", stem).strip()
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
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return meta, text
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() in ("---", "..."):
            return meta, "\n".join(lines[i + 1:])
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().strip('"').strip("'")
            if v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
            meta[k.strip().lower()] = v
    return {}, text


def meta_get(meta: dict, *keys, default=""):
    for k in keys:
        if meta.get(k):
            return meta[k]
    return default


def as_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        return v
    return [x.strip() for x in str(v).split(",") if x.strip()]


def truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "tak", "true", "yes", "y")


def git_first_dates(content_dir: Path) -> dict[str, str]:
    """Data dodania każdego pliku do repozytorium (najstarszy commit, z wykrywaniem przeniesień)."""
    out: dict[str, str] = {}
    try:
        res = subprocess.run(
            ["git", "-c", "core.quotepath=off", "log", "--format=@%cs", "--name-only", "-M"],
            cwd=ROOT, capture_output=True, text=True, check=True)
    except Exception:
        return out
    current = None
    by_name: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if line.startswith("@"):
            current = line[1:]
        elif line.strip() and current:
            p = line.strip()
            out[str((ROOT / p).resolve())] = current  # nadpisywane => zostaje najstarsza data
            by_name[Path(p).name] = current
    out["__by_name__"] = by_name  # type: ignore[assignment]
    return out


def intrinsic_date(f: Path, kind: str) -> str:
    """Data zapisana w samym pliku (metadane PDF/DOCX/ZIP)."""
    try:
        if kind == "pdf":
            with open(f, "rb") as fh:
                head = fh.read(2_000_000)
            m = re.search(rb"/CreationDate\s*\(D:(\d{4})(\d{2})(\d{2})", head) or \
                re.search(rb"<xmp:CreateDate>(\d{4})-(\d{2})-(\d{2})", head)
            if m:
                return "-".join(x.decode() for x in m.groups())
        elif kind == "word" and f.suffix.lower() == ".docx":
            with zipfile.ZipFile(f) as z:
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
            m = re.search(r"<dcterms:created[^>]*>(\d{4}-\d{2}-\d{2})", core)
            if m and not m.group(1).startswith(("1980", "2006")):
                return m.group(1)
        elif kind == "archive" and f.suffix.lower() == ".zip":
            with zipfile.ZipFile(f) as z:
                dates = [i.date_time for i in z.infolist()]
            if dates:
                y, mo, d = max(dates)[:3]
                if y > 1980:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
    except Exception:
        pass
    return ""


def text_date(text: str) -> str:
    """Data w treści dokumentu: „Oct 5, 2026”, „2026-10-05” albo „5.10.2026” w pierwszych liniach."""
    head = "\n".join(text.strip().split("\n")[:6])
    m = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2}), (\d{4})", head)
    if m:
        return f"{int(m.group(3)):04d}-{MONTHS_EN[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", head)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", head)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def file_kind(ext: str) -> str:
    ext = ext.lower()
    for k, (exts, _, _) in KINDS.items():
        if ext in exts:
            return k
    return "other"


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n} B"


def strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def summarize(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def plural(n: int) -> str:
    if n == 1:
        return "materiał"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "materiały"
    return "materiałów"


def fmt_date(d: str) -> str:
    try:
        y, m, dd = d.split("-")
        return f"{int(dd)} {MONTHS_PL[int(m)][:3]} {y}"
    except Exception:
        return d


# --------------------------------------------------------------------------- model

@dataclass
class Item:
    rel: str            # ścieżka względem content/
    src: Path
    collection: str
    folder: str         # podkatalog wewnątrz działu ("" = główny)
    kind: str
    title: str
    href: str           # ścieżka względem korzenia strony
    date: str = ""
    summary: str = ""
    tags: list = field(default_factory=list)
    size: int = 0
    order: str = ""
    body_html: str = ""
    toc_html: str = ""
    thumb: str = ""
    alts: list = field(default_factory=list)   # [(etykieta, href)]
    spoiler: bool = False

    @property
    def stem_key(self):
        return (self.collection, self.folder, Path(self.rel).stem.lower())

    @property
    def opens_new_tab(self):
        return self.kind not in ("doc", "image")


@dataclass
class Collection:
    slug: str
    dirname: str
    title: str
    description_html: str = ""
    summary: str = ""
    period: str = ""
    order: str = ""
    spoiler: bool = False
    items: list = field(default_factory=list)


# --------------------------------------------------------------------------- build

class Builder:
    def __init__(self, content: Path, out: Path):
        self.content = content
        self.out = out
        self.inplace = out.resolve() == ROOT
        # ścieżka do materiałów względem korzenia strony
        self.raw_prefix = os.path.relpath(content, ROOT).replace("\\", "/") + "/" if self.inplace else "content/"
        self.site = {"title": "Kampania", "subtitle": "", "lang": "pl", "footer": "", "hero": "", "logo": ""}
        cfg = content / "_site.json"
        if cfg.exists():
            try:
                self.site.update(json.loads(cfg.read_text(encoding="utf-8")))
            except json.JSONDecodeError as e:
                print(f"⚠ _site.json: błąd JSON ({e}) — używam domyślnych ustawień")
        self.collections: dict[str, Collection] = {}
        self.items: list[Item] = []
        self.dates = git_first_dates(content)
        self.md_paths: dict[str, str] = {}  # rel .md -> href strony
        self.used_thumbs: set[str] = set()

    # ---- ścieżki
    def raw_href(self, rel: str) -> str:
        return self.raw_prefix + rel

    # ---- markdown
    def md(self, text: str) -> tuple[str, str]:
        conv = md_lib.Markdown(
            extensions=["extra", "toc", "sane_lists", "smarty"],
            extension_configs={"toc": {"permalink": "#", "permalink_class": "anchor", "toc_depth": "2-4"}},
            output_format="html")
        body = conv.convert(text)
        return body, getattr(conv, "toc", "")

    def rewrite_links(self, body: str, item: Item) -> str:
        """Względne linki w dokumencie → poprawne ścieżki na stronie (.md → wygenerowana strona)."""
        base = Path(item.rel).parent
        page_dir = os.path.dirname(item.href)

        def repl(m):
            attr, q, target = m.group(1), m.group(2), m.group(3)
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^#|^/", target):
                return m.group(0)
            path, _, frag = target.partition("#")
            norm = os.path.normpath(str(base / unquote(path))).replace("\\", "/")
            if norm.startswith(".."):
                return m.group(0)
            dest = self.md_paths.get(norm) or self.raw_href(norm)
            new = url(os.path.relpath(dest, page_dir or ".").replace("\\", "/")) + (("#" + frag) if frag else "")
            return f"{attr}={q}{new}{q}"

        return re.sub(r'(href|src)=(["\'])([^"\']+)\2', repl, body)

    @staticmethod
    def callouts(body: str) -> str:
        """Bloki jak w PDF: > cytat = „Do przeczytania”, **Notka MG.** = notka, **Sekret…** = sekret MG."""
        body = re.sub(r"<p><strong>(Notka(?: MG)?\.?)</strong>", r'<p class="box note"><strong>\1</strong>', body)
        body = re.sub(r"<p><strong>(Sekret[^<]*)</strong>:?\s*",
                      r'<p class="box secret"><span class="box-label">\1</span>', body)
        body = re.sub(r"<p><strong>(Wpis w księdze[^<]*)</strong>:?\s*",
                      r'<p class="box ledger"><span class="box-label">\1</span>', body)
        body = body.replace("<blockquote>", '<blockquote class="box read"><span class="box-label">Do przeczytania</span>')
        return body

    # ---- skanowanie
    def scan(self):
        if not self.content.exists():
            sys.exit(f"Brak katalogu {self.content}")
        for d in sorted(p for p in self.content.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            self.add_collection(d)
        loose = [p for p in self.content.iterdir()
                 if p.is_file() and p.name not in META_FILES | SKIP_NAMES and not p.name.startswith(".")]
        if loose:
            col = Collection(slug="inne", dirname="", title="Inne", order="zzz")
            self.collections[col.slug] = col
            for f in sorted(loose):
                self.add_file(col, f, {})
        self.merge_alternates()
        for it in self.items:
            if it.kind == "doc":
                _, body = parse_front_matter(it.src.read_text(encoding="utf-8", errors="replace"))
                html_body, toc = self.md(body)
                it.body_html = self.callouts(self.rewrite_links(html_body, it))
                it.toc_html = toc if toc.count("<li") >= 2 else ""

    def add_collection(self, d: Path):
        title, desc_html, summary, period, spoiler = pretty_name(d.name), "", "", "", False
        info = d / "_info.md"
        if info.exists():
            meta, body = parse_front_matter(info.read_text(encoding="utf-8", errors="replace"))
            title = meta_get(meta, "title", "tytul", "tytuł", default=title)
            period = meta_get(meta, "okres", "period")
            spoiler = truthy(meta_get(meta, "spoiler", "tylko_mg", default="nie"))
            body = body.strip()
            m = re.match(r"^#\s+(.+)\n?", body)
            if m:
                if not meta_get(meta, "title", "tytul", "tytuł"):
                    title = m.group(1).strip()
                body = body[m.end():].strip()
            if body:
                desc_html, _ = self.md(body)
                summary = summarize(strip_tags(desc_html), 220)
            summary = meta_get(meta, "opis", "description", default=summary)
        opisy = {}
        if (d / "_opisy.json").exists():
            try:
                opisy = json.loads((d / "_opisy.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"⚠ {d.name}/_opisy.json: błąd JSON ({e})")
        slug = slugify(d.name)
        base, n = slug, 2
        while slug in self.collections:
            slug, n = f"{base}-{n}", n + 1
        col = Collection(slug=slug, dirname=d.name, title=title, description_html=desc_html,
                         summary=summary, period=period, order=d.name, spoiler=spoiler)
        self.collections[slug] = col
        # katalog z index.html = cała strona/aplikacja: jeden wpis, reszta plików tylko dostępna
        site_dirs = sorted({p.parent for p in d.rglob("*") if p.name.lower() in ("index.html", "index.htm")},
                           key=lambda p: len(p.parts))
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.name in SKIP_NAMES:
                continue
            if any(part.startswith(".") for part in f.relative_to(d).parts):
                continue
            if f.parent == d and f.name in META_FILES:
                continue
            owner = next((s for s in site_dirs if f.parent == s or s in f.parents), None)
            if owner is not None and not (f.parent == owner and f.name.lower() in ("index.html", "index.htm")):
                continue
            self.add_file(col, f, opisy)

    def add_file(self, col: Collection, f: Path, opisy: dict):
        rel = f.relative_to(self.content).as_posix()
        kind = file_kind(f.suffix)
        inner = list(Path(rel).parts[1:-1]) if col.dirname else []
        is_site = f.name.lower() in ("index.html", "index.htm")
        if is_site and inner:
            inner = inner[:-1]
        folder = "/".join(inner)
        date, title, summary, tags = "", pretty_name(f.stem), "", []
        if is_site:
            title = pretty_name(f.parent.name)
        m = DATE_PREFIX_RE.match(f.name)
        if m:
            date = m.group(1)
        href = self.raw_href(rel)

        if kind == "doc":
            raw = f.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_front_matter(raw)
            h = re.search(r"^#\s+(.+)$", body, re.M)
            title = meta_get(meta, "title", "tytul", "tytuł", default=h.group(1).strip() if h else title)
            date = meta_get(meta, "date", "data", default=date) or text_date(re.sub(r"^#.*\n", "", body.strip()))
            tags = as_list(meta_get(meta, "tags", "tagi"))
            summary = meta_get(meta, "opis", "description")
            if not summary:
                body_nodate = "\n".join(l for l in body.split("\n")[:8] if not text_date(l)) + "\n" + "\n".join(body.split("\n")[8:])
                paras = [p for p in re.split(r"\n\s*\n", body_nodate)
                         if p.strip() and not p.lstrip().startswith(("#", "!", "|", "```", "<", "-", "*", ">"))
                         and not text_date(p) and len(p.strip()) > 30]
                if paras:
                    summary = summarize(re.sub(r"[*_`]", "", re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", paras[0])))
            href = "p/" + rel[: -len(f.suffix)] + ".html"
            self.md_paths[rel] = href
        elif kind == "html":
            try:
                t = f.read_text(encoding="utf-8", errors="replace")
                tm = re.search(r"<title[^>]*>(.*?)</title>", t, re.I | re.S)
                if tm and tm.group(1).strip():
                    title = html.unescape(re.sub(r"\s+", " ", tm.group(1)).strip())
                dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', t, re.I)
                if dm:
                    summary = html.unescape(dm.group(1))
                else:
                    for p in re.findall(r"<p[^>]*>(.*?)</p>", t, re.S | re.I):
                        txt = re.sub(r"\s+", " ", strip_tags(p)).strip()
                        if len(txt) > 50:
                            summary = summarize(txt)
                            break
            except OSError:
                pass

        # opis z _opisy.json (klucz: ścieżka wewnątrz działu albo sama nazwa pliku)
        inner_rel = "/".join(Path(rel).parts[1:]) if col.dirname else rel
        o = opisy.get(inner_rel) or opisy.get(f.name)
        if isinstance(o, str):
            summary = o
        elif isinstance(o, dict):
            title = o.get("title") or o.get("tytuł") or title
            summary = o.get("opis") or o.get("description") or summary
            date = o.get("data") or o.get("date") or date
            tags = as_list(o.get("tagi") or o.get("tags")) or tags

        if not date:
            date = intrinsic_date(f, kind)
        if not date:
            date = self.dates.get(str(f.resolve()), "") or self.dates.get("__by_name__", {}).get(f.name, "")
        if not date:
            date = dt.date.fromtimestamp(f.stat().st_mtime).isoformat()

        it = Item(rel=rel, src=f, collection=col.slug, folder=folder, kind=kind, title=title, href=href,
                  date=str(date), summary=summary, tags=tags, size=f.stat().st_size,
                  order=rel.lower(), spoiler=col.spoiler)
        if kind == "image":
            it.thumb = self.make_thumb(f)
        col.items.append(it)
        self.items.append(it)

    def merge_alternates(self):
        """X.html + X.pdf → jeden wpis z dodatkowym linkiem „PDF”; X.webp + X.svg → obraz + „SVG”."""
        groups: dict[tuple, list[Item]] = {}
        for it in self.items:
            groups.setdefault(it.stem_key, []).append(it)
        drop = set()
        for key, its in groups.items():
            if len(its) < 2:
                continue
            its.sort(key=lambda x: (PRIMARY_ORDER.index(x.kind), Path(x.rel).suffix.lower() not in RASTER))
            primary = its[0]
            for other in its[1:]:
                label = Path(other.rel).suffix.lstrip(".").upper()
                primary.alts.append((label, other.href))
                if not primary.summary and other.summary:
                    primary.summary = other.summary
                drop.add(id(other))
            if primary.kind in ("html", "doc", "image"):
                primary.alts.insert(0, ({"html": "Otwórz", "doc": "Czytaj", "image": "Obraz"}[primary.kind], primary.href))
        if drop:
            self.items = [i for i in self.items if id(i) not in drop]
            for c in self.collections.values():
                c.items = [i for i in c.items if id(i) not in drop]

    def make_thumb(self, f: Path) -> str:
        if Image is None or f.suffix.lower() not in RASTER or f.stat().st_size < 150_000:
            return ""
        h = hashlib.md5(f.read_bytes()).hexdigest()[:16]
        rel = f"t/{h}.webp"
        dest = self.out / rel
        self.used_thumbs.add(dest.name)
        if not dest.exists():
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(f) as im:
                    im = im.convert("RGBA") if im.mode in ("P", "LA") else im
                    im.thumbnail((640, 640))
                    im.save(dest, "WEBP", quality=80, method=5)
            except Exception as e:  # pragma: no cover
                print(f"⚠ miniatura {f.name}: {e}")
                return ""
        return rel

    # ---- elementy strony
    def ordered_collections(self) -> list[Collection]:
        return sorted(self.collections.values(), key=lambda c: c.order)

    def col_index(self, c: Collection) -> int:
        return self.ordered_collections().index(c) + 1

    def nav(self, root: str, active: str) -> str:
        links = [("index.html", "Jednostrzał (MG)", "mg"), (HOME, "Biblioteka", "home"), ("os-czasu.html", "Oś czasu", "timeline"),
                 ("wszystko.html", "Spis", "all")]
        main = "".join(f'<a href="{root}{h}" class="{"active" if active == k else ""}">{t}</a>' for h, t, k in links)
        cols = "".join(
            f'<a href="{root}e/{c.slug}/index.html" class="{"active" if active == "c:" + c.slug else ""}'
            f'{" spoiler-link" if c.spoiler else ""}">{esc(c.title)}</a>'
            for c in self.ordered_collections())
        logo = (f'<img class="logo-img" src="{root}{url(self.thumb_or_raw(self.site["logo"]))}" alt="">'
                if self.site.get("logo") else "")
        return f"""
<header class="topbar">
  <a class="brand" href="{root}{HOME}">{logo}<span>{esc(self.site.get('short') or self.site['title'])}</span></a>
  <button class="menu-btn" aria-label="Menu" aria-expanded="false" data-menu>☰</button>
  <nav class="mainnav" data-nav>{main}<span class="sep" aria-hidden="true"></span>{cols}</nav>
  <div class="tools">
    <button class="icon-btn" data-search-open aria-label="Szukaj" title="Szukaj (/)"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg></button>
    <button class="icon-btn" data-theme-toggle aria-label="Zmień motyw" title="Jasny / ciemny"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/></svg></button>
  </div>
</header>"""

    def thumb_or_raw(self, content_rel: str) -> str:
        f = self.content / content_rel
        if not f.exists():
            return self.raw_href(content_rel)
        return self.make_thumb(f) or self.raw_href(content_rel)

    def page(self, root: str, title: str, body: str, active: str = "", description: str = "",
             spoiler: bool = False, running: str = "") -> str:
        full_title = title if title == self.site["title"] else f"{title} · {self.site['title']}"
        footer = self.site.get("footer") or ""
        built = dt.datetime.now(dt.timezone.utc).strftime("%d.%m.%Y")
        gate = ""
        if spoiler:
            gate = f"""
<div class="gate" data-gate hidden>
  <div class="box secret gate-box">
    <span class="box-label">Sekret MG</span>
    <h2>Tu są spoilery</h2>
    <p>Scenariusze, sekrety Stajni i notatki prowadzącego. Rzeczy, których gracz nie może zobaczyć.</p>
    <div class="actions"><a class="btn" href="{root}{HOME}">Wracam</a><button class="btn primary" data-gate-ok>Jestem MG — pokaż</button></div>
  </div>
</div>"""
        left = "Tylko dla MG" if spoiler else (self.site.get("kicker") or self.site["title"])
        right = running or title
        return f"""<!doctype html>
<html lang="{esc(self.site.get('lang', 'pl'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description or self.site['subtitle'])}">
<link rel="icon" href="{root}{url(self.thumb_or_raw(self.site['logo'])) if self.site.get('logo') else 'data:,'}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Alfa+Slab+One&family=Courier+Prime:wght@400;700&family=EB+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap">
<link rel="stylesheet" href="{root}assets/style.css">
<script>try{{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
<body data-root="{root}"{' data-spoiler' if spoiler else ''}>
{self.nav(root, active)}
<main class="wrap">
{body}
</main>
<footer class="foot">
  <div class="wrap">
    <span class="run run-left">{esc(left)}</span>
    <span class="run run-right">{esc(right)}</span>
  </div>
  <div class="wrap foot-note">{esc(footer) + ' · ' if footer else ''}stan na {built} · {len(self.items)} {plural(len(self.items))}</div>
</footer>{gate}
<div class="search-modal" data-search-modal hidden>
  <div class="search-box" role="dialog" aria-label="Wyszukiwarka">
    <input type="search" placeholder="Szukaj we wszystkich materiałach…" data-search-input autocomplete="off">
    <ul class="search-results" data-search-results></ul>
    <p class="search-hint">Enter — otwórz · Esc — zamknij</p>
  </div>
</div>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""

    def item_card(self, it: Item, root: str, show_col: bool = False) -> str:
        col = self.collections[it.collection]
        thumb = ""
        if it.kind == "image":
            thumb = f'<img class="thumb" src="{root}{url(it.thumb or it.href)}" alt="" loading="lazy">'
        meta = [f'<span class="label">{TYPE_LABEL[it.kind]}</span>']
        if show_col:
            meta.append(f'<span class="label col">{esc(col.title)}</span>')
        if it.date:
            meta.append(f'<time datetime="{esc(it.date)}">{esc(fmt_date(it.date))}</time>')
        if it.kind not in ("doc", "html"):
            meta.append(f'<span>{human_size(it.size)}</span>')
        tags = "".join(f'<span class="tag">#{esc(t)}</span>' for t in it.tags)
        target = ' target="_blank" rel="noopener"' if it.opens_new_tab else ""
        alts = ""
        if it.alts:
            alts = '<div class="alts">' + "".join(
                f'<a href="{root}{url(h)}"{"" if lbl in ("Czytaj", "Obraz") else " target=\"_blank\" rel=\"noopener\""}>{esc(lbl)}</a>'
                for lbl, h in it.alts) + "</div>"
        text = (it.title + " " + it.summary + " " + " ".join(it.tags) + " " + it.rel).lower()
        return f"""<article class="card kind-{it.kind}{' is-secret' if it.spoiler else ''}" data-kind="{it.kind}" data-col="{it.collection}" data-text="{esc(text)}">
  {thumb}
  <div class="card-body">
    <h3><a class="card-link" href="{root}{url(it.href)}"{target}{' data-lightbox' if it.kind == 'image' else ''} title="{esc(it.title)}">{esc(it.title)}</a></h3>
    {f'<p>{esc(it.summary)}</p>' if it.summary else ''}
    <div class="meta">{''.join(meta)}{tags}</div>
    {alts}
  </div>
</article>"""

    def gallery(self, items: list[Item], root: str) -> str:
        return '<div class="gallery">' + "".join(
            f'<figure><a href="{root}{url(x.href)}" data-lightbox title="{esc(x.title)}"><img src="{root}{url(x.thumb or x.href)}" alt="{esc(x.title)}" loading="lazy"></a><figcaption>{esc(x.title)}</figcaption></figure>'
            for x in items) + "</div>"

    def chapter_head(self, kicker: str, title: str, subtitle: str = "", secret: bool = False) -> str:
        return f"""<header class="chapter{' is-secret' if secret else ''}">
  {f'<p class="kicker">{kicker}</p>' if kicker else ''}
  <h1 class="display">{esc(title)}</h1>
  {f'<p class="subtitle">{subtitle}</p>' if subtitle else ''}
</header>"""

    # ---- strony
    def render_home(self):
        root = ""
        intro_html = ""
        idx = self.content / "_index.md"
        if idx.exists():
            _, body = parse_front_matter(idx.read_text(encoding="utf-8", errors="replace"))
            intro_html, _ = self.md(body)
        cols = self.ordered_collections()
        rows = []
        for i, c in enumerate(cols, 1):
            rows.append(f"""
<li class="toc-row{' is-secret' if c.spoiler else ''}">
  <a href="e/{c.slug}/index.html">
    <span class="toc-title">{esc(c.title)}{'<span class="stamp-inline">tylko MG</span>' if c.spoiler else ''}</span>
    <span class="toc-num">{len(c.items):02d}</span>
  </a>
  {f'<p class="toc-desc">{esc(c.summary)}</p>' if c.summary else ''}
</li>""")
        public = [x for x in self.items if not x.spoiler and x.kind != "image"]
        recent = sorted(public, key=lambda x: (x.date, x.rel), reverse=True)[:6]
        logo = (f'<img class="cover-emblem" src="{url(self.thumb_or_raw(self.site["logo"]))}" alt="">'
                if self.site.get("logo") else "")
        body = f"""
<section class="cover">
  <div class="cover-text">
    <p class="kicker">{esc(self.site.get('kicker', ''))}</p>
    <h1 class="display xl">{esc(self.site['title'])}</h1>
    <p class="subtitle">{esc(self.site['subtitle'])}</p>
    {f'<p class="stamp">{esc(self.site["stamp"])}</p>' if self.site.get('stamp') else ''}
  </div>
  {logo}
</section>
<section class="contents">
  <h2 class="h-slab">Spis treści</h2>
  <ol class="toc">{''.join(rows) or '<li class="empty">Brak materiałów — dodaj pliki do katalogu <code>content/</code>.</li>'}</ol>
</section>
{f'<aside class="box read"><span class="box-label">Do przeczytania</span>{intro_html}</aside>' if intro_html.strip() else ''}
<aside class="legend">
  <div class="box read"><span class="box-label">Do przeczytania</span><p><em>Tekst do przeczytania graczom.</em></p></div>
  <div class="box note"><p><strong>Notka MG.</strong> Wskazówki prowadzenia, nie dla graczy.</p></div>
  <div class="box secret"><span class="box-label">Sekret MG</span><p>Rzeczy, których gracz nie może zobaczyć.</p></div>
</aside>
{f'<section><h2 class="h-slab">Najnowsze</h2><div class="grid">{"".join(self.item_card(it, root, True) for it in recent)}</div></section>' if recent else ''}
"""
        page = self.page(root, self.site["title"], body, "home", running="Spis treści")
        self.write(HOME, page)
        mg = ROOT / "wydanie" / "interaktywny.html"
        self.write("index.html", mg.read_text(encoding="utf-8") if mg.exists() else page)

    def render_collection(self, c: Collection):
        root = "../../"
        groups: dict[str, list[Item]] = {}
        for it in sorted(c.items, key=lambda x: x.order):
            groups.setdefault(it.folder, []).append(it)
        cols = self.ordered_collections()
        i = cols.index(c)
        prev_c = cols[i - 1] if i > 0 else None
        next_c = cols[i + 1] if i + 1 < len(cols) else None
        folders = sorted(groups, key=lambda f: (f != "", ("starsze" in f.lower() or "archiw" in f.lower()), f.lower()))
        sections, toc = [], []
        for folder in folders:
            items = groups[folder]
            imgs = [x for x in items if x.kind == "image" and not x.alts]
            rest = [x for x in items if x not in imgs]
            head = ""
            if folder:
                name = " / ".join(pretty_name(p) for p in folder.split("/"))
                fid = slugify(folder)
                head = f'<h2 class="h-slab" id="{fid}">{esc(name)}</h2>'
                toc.append(f'<a href="#{fid}">{esc(name)}</a>')
            cards = ('<div class="grid">' + "".join(self.item_card(x, root) for x in rest) + "</div>") if rest else ""
            sections.append(f"<section>{head}{cards}{self.gallery(imgs, root) if imgs else ''}</section>")
        pager = f"""<nav class="pager">
  {f'<a href="../{prev_c.slug}/index.html" class="prev"><span class="label">Poprzedni dział</span>{esc(prev_c.title)}</a>' if prev_c else '<span></span>'}
  {f'<a href="../{next_c.slug}/index.html" class="next"><span class="label">Następny dział</span>{esc(next_c.title)}</a>' if next_c else '<span></span>'}
</nav>"""
        kicker = f"Dział {i + 1:02d} z {len(cols):02d}" + (f" · {esc(c.period)}" if c.period else "")
        desc = f'<div class="prose lead-prose">{c.description_html}</div>' if c.description_html else ''
        if c.spoiler and desc:
            desc = f'<div class="box secret"><span class="box-label">Sekret MG</span>{c.description_html}</div>'
        body = f"""
<nav class="crumbs"><a href="{root}{HOME}">Spis treści</a> / <span>{esc(c.title)}</span></nav>
{self.chapter_head(kicker, c.title, f'{len(c.items)} {plural(len(c.items))}', c.spoiler)}
{desc}
{f'<nav class="subnav">{"".join(toc)}</nav>' if len(toc) > 1 else ''}
{''.join(sections) if c.items else '<p class="empty">Ten dział jest jeszcze pusty.</p>'}
{pager}
"""
        self.write(f"e/{c.slug}/index.html",
                   self.page(root, c.title, body, "c:" + c.slug, c.summary, spoiler=c.spoiler,
                             running=f"{c.title} · {i + 1}"))

    def render_doc(self, it: Item):
        root = "../" * it.href.count("/")
        c = self.collections[it.collection]
        siblings = sorted([x for x in c.items if x.kind == "doc"], key=lambda x: x.order)
        i = siblings.index(it)
        prev_d = siblings[i - 1] if i > 0 else None
        next_d = siblings[i + 1] if i + 1 < len(siblings) else None
        crumbs = [f'<a href="{root}{HOME}">Spis treści</a>', f'<a href="{root}e/{c.slug}/index.html">{esc(c.title)}</a>']
        if it.folder:
            crumbs.append(f'<a href="{root}e/{c.slug}/index.html#{slugify(it.folder)}">'
                          f'{esc(" / ".join(pretty_name(p) for p in it.folder.split("/")))}</a>')
        tags = "".join(f'<span class="tag">#{esc(t)}</span>' for t in it.tags)
        body_html = re.sub(r'^\s*<h1[^>]*>.*?</h1>', "", it.body_html, count=1, flags=re.S)
        # krótki pierwszy akapit (data · autor, podtytuł) → podtytuł kursywą, jak w PDF
        subtitle = ""
        m = re.match(r"\s*<p>(.*?)</p>", body_html, re.S)
        if m and len(strip_tags(m.group(1)).strip()) <= 90 and "<a " not in m.group(1):
            subtitle = m.group(1).strip()
            body_html = body_html[m.end():]
        source = os.path.relpath(self.raw_href(it.rel), os.path.dirname(it.href)).replace("\\", "/")
        alts = "".join(f'<a href="{root}{url(h)}" target="_blank" rel="noopener">{esc(l)}</a>'
                       for l, h in it.alts if l != "Czytaj")
        kicker = esc(c.title) + (" · " + esc(" / ".join(pretty_name(p) for p in it.folder.split("/"))) if it.folder else "")
        body = f"""
<nav class="crumbs">{' / '.join(crumbs)}</nav>
<div class="doc-layout{' has-toc' if it.toc_html else ''}">
  <article class="prose doc">
    {self.chapter_head(kicker, it.title, subtitle, it.spoiler)}
    <div class="doc-meta">{f'<time datetime="{esc(it.date)}">{esc(fmt_date(it.date))}</time>' if it.date else ''}{tags}
      <span class="doc-links">{alts}<a href="{url(source)}" download>pobierz .md</a></span></div>
    {body_html}
  </article>
  {f'<aside class="toc-side"><span class="label">Spis treści</span>{it.toc_html}</aside>' if it.toc_html else ''}
</div>
<nav class="pager">
  {f'<a href="{root}{url(prev_d.href)}" class="prev"><span class="label">Poprzedni</span>{esc(prev_d.title)}</a>' if prev_d else '<span></span>'}
  {f'<a href="{root}{url(next_d.href)}" class="next"><span class="label">Następny</span>{esc(next_d.title)}</a>' if next_d else '<span></span>'}
</nav>
"""
        self.write(it.href, self.page(root, it.title, body, "c:" + c.slug, it.summary, spoiler=it.spoiler,
                                      running=f"{it.title} · {c.title}"))

    def render_all(self):
        root = ""
        cols = self.ordered_collections()
        items = sorted(self.items, key=lambda x: (cols.index(self.collections[x.collection]), x.order))
        kinds = sorted({it.kind for it in items}, key=PRIMARY_ORDER.index)
        f_col = "".join(f'<option value="{c.slug}">{esc(c.title)}</option>' for c in cols)
        f_kind = "".join(f'<option value="{k}">{TYPE_LABEL[k]}</option>' for k in kinds)
        spoiler_cols = [c.slug for c in cols if c.spoiler]
        rows = []
        for it in items:
            col = self.collections[it.collection]
            target = ' target="_blank" rel="noopener"' if it.opens_new_tab else ""
            alts = " ".join(f'<a class="alt" href="{url(h)}"{"" if l in ("Czytaj", "Obraz") else " target=\"_blank\" rel=\"noopener\""}>{esc(l)}</a>'
                            for l, h in it.alts if l not in ("Czytaj", "Otwórz", "Obraz"))
            text = (it.title + " " + it.summary + " " + " ".join(it.tags) + " " + it.rel).lower()
            folder = " / ".join(pretty_name(p) for p in it.folder.split("/")) if it.folder else ""
            rows.append(f"""<tr class="card{' is-secret' if it.spoiler else ''}" data-kind="{it.kind}" data-col="{it.collection}" data-text="{esc(text)}">
  <td class="c-title"><a href="{url(it.href)}"{target}{' data-lightbox' if it.kind == 'image' else ''}>{esc(it.title)}</a> {alts}
    {f'<span class="row-sub">{esc(it.summary)}</span>' if it.summary else ''}</td>
  <td>{esc(col.title)}{f'<span class="row-sub">{esc(folder)}</span>' if folder else ''}</td>
  <td class="c-kind">{TYPE_LABEL[it.kind]}</td>
  <td class="c-date"><time datetime="{esc(it.date)}">{esc(it.date)}</time></td>
</tr>""")
        body = f"""
{self.chapter_head("Wszystkie materiały", "Spis", f'<span data-count>{len(items)}</span> z {len(items)} — filtruj, szukaj, otwieraj.')}
<div class="filters" data-filters data-spoiler-cols="{' '.join(spoiler_cols)}">
  <input type="search" placeholder="Filtruj po nazwie, opisie, tagu…" data-filter-text>
  <select data-filter-col><option value="">Wszystkie działy</option>{f_col}</select>
  <select data-filter-kind><option value="">Wszystkie typy</option>{f_kind}</select>
  {'<label class="check"><input type="checkbox" data-filter-spoiler> pokaż materiały MG</label>' if spoiler_cols else ''}
</div>
<div class="table-wrap">
<table class="doc-table index-table">
  <thead><tr><th>Materiał</th><th>Dział</th><th>Typ</th><th>Data</th></tr></thead>
  <tbody data-filter-grid>{''.join(rows)}</tbody>
</table>
</div>
<p class="empty" data-filter-empty hidden>Nic nie pasuje do filtrów.</p>
"""
        self.write("wszystko.html", self.page(root, "Spis", body, "all", running="Spis materiałów"))

    def render_timeline(self):
        root = ""
        items = sorted([x for x in self.items if not x.spoiler], key=lambda x: (x.date, x.order))
        by_month: dict[str, list[Item]] = {}
        for it in items:
            by_month.setdefault(it.date[:7], []).append(it)
        blocks = []
        for ym, its in by_month.items():
            try:
                y, m = ym.split("-")
                label = f"{MONTHS_PL[int(m)].capitalize()} {y}"
            except Exception:
                label = ym or "bez daty"
            entries = "".join(f"""
<li class="tl-item">
  <time datetime="{esc(it.date)}">{esc(it.date[8:10])}.{esc(it.date[5:7])}</time>
  <span class="tl-what"><a href="{url(it.href)}"{' target="_blank" rel="noopener"' if it.opens_new_tab else ''}{' data-lightbox' if it.kind == 'image' else ''}>{esc(it.title)}</a></span>
  <span class="tl-where">{esc(self.collections[it.collection].title)} · {TYPE_LABEL[it.kind]}</span>
</li>""" for it in its)
            blocks.append(f"""
<section class="tl-month">
  <h2 class="h-slab">{esc(label)} <span class="count">{len(its)}</span></h2>
  <ol class="tl-list">{entries}</ol>
</section>""")
        body = f"""
{self.chapter_head("Od najstarszych do najnowszych", "Oś czasu", "Data z dokumentu, z metadanych pliku albo z chwili dodania do repozytorium. Materiały MG są pominięte.")}
<div class="timeline">{''.join(blocks) or '<p class="empty">Brak materiałów.</p>'}</div>
"""
        self.write("os-czasu.html", self.page(root, "Oś czasu", body, "timeline", running="Oś czasu"))

    def render_404(self):
        body = self.chapter_head("Błąd 404", "Pusto tu", "Tej strony nie ma — może drzwi zamknęły się na dobre.") + \
            f'<p class="actions"><a class="btn primary" href="{HOME}">Wróć do spisu treści</a></p>'
        out = self.page("", "Nie znaleziono", body)
        out = out.replace("<head>", """<head>
<script>(function(){var p=location.pathname.split('/').filter(Boolean);var b=(location.hostname.endsWith('github.io')&&p.length)?'/'+p[0]+'/':'/';document.write('<base href="'+b+'">');})();</script>""", 1)
        self.write("404.html", out)

    def write_search_index(self):
        data = []
        for it in self.items:
            text = it.summary
            if it.kind == "doc":
                clean = re.sub(r'<a class="anchor"[^>]*>#</a>', "", it.body_html)
                clean = re.sub(r"<h1[^>]*>.*?</h1>", "", clean, count=1, flags=re.S)
                text = summarize(strip_tags(clean), 4000)
            data.append({"t": it.title, "h": it.href, "k": it.kind, "c": self.collections[it.collection].title,
                         "d": it.date, "s": text, "g": it.tags, "p": it.rel, "x": 1 if it.spoiler else 0})
        self.write("search.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    # ---- io
    def write(self, rel: str, text: str):
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def clean(self):
        self.out.mkdir(parents=True, exist_ok=True)
        for name in GENERATED:
            p = self.out / name
            if name == "t":
                continue  # miniatury zostają (cache); nieużywane usuwamy na końcu
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()

    def run(self):
        self.clean()
        self.scan()
        if not self.inplace:
            shutil.copytree(self.content, self.out / "content",
                            ignore=shutil.ignore_patterns(".*", *SKIP_NAMES), dirs_exist_ok=True)
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
        tdir = self.out / "t"
        if tdir.exists():
            for f in tdir.iterdir():
                if f.name not in self.used_thumbs:
                    f.unlink()
        print(f"✔ Zbudowano stronę w {self.out} — {len(self.collections)} działów, {len(self.items)} materiałów")
        for c in self.ordered_collections():
            print(f"   • {c.title}: {len(c.items)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--content", default=str(ROOT / "content"))
    ap.add_argument("--out", default=str(ROOT), help="katalog wynikowy (domyślnie: katalog główny repozytorium)")
    a = ap.parse_args()
    Builder(Path(a.content).resolve(), Path(a.out).resolve()).run()


if __name__ == "__main__":
    main()
