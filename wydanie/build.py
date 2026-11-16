#!/usr/bin/env python3
"""
Składa zbiorcze wydanie „Jednostrzał i sesje zero” (PDF + HTML) z rozdziałów w wydanie/rozdzialy/.

Składnia rozdziałów: Markdown + kilka dodatków:
  ::: read [Etykieta]        ramka „Do przeczytania” (beżowa, kursywa)
  ::: note                   „Notka MG.” (szara)
  ::: ledger [Etykieta]      „Wpis w księdze” (kremowa, brązowa krawędź)
  ::: secret [Etykieta]      „Sekret MG” (czerwona przerywana)
  ::: box [Etykieta]         zwykła ramka z etykietą
  ::: cols                   dwie kolumny (rozdziel linią: |||)
  :::                        koniec bloku
  {{include: ścieżka}}       wstawia plik .md z repozytorium (np. dokument źródłowy bez zmian)
  {{handout: ścieżka.html}}  wstawia oczyszczoną treść handoutu HTML
  {{img: ścieżka | podpis | klasa}}   ilustracja (ścieżka względem content/)

Front matter rozdziału:
  typ: czesc | rozdzial | dodatek
  tytul, podtytul, kicker, stopka (żywa pagina), id

Użycie: python wydanie/build.py   (wymaga: markdown, weasyprint 70)
"""
from __future__ import annotations

import datetime as dt
import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import markdown

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
OUT_DIR = CONTENT / "05-dla-mg"
OUT_NAME = "FoE_Jednostrzal_i_sesje_zero_MG"
STAN = dt.date.today().strftime("%d.%m.%Y")

LABELS = {"read": "Do przeczytania", "ledger": "Wpis w księdze", "secret": "Sekret MG", "note": "", "box": ""}


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def slug(s: str) -> str:
    t = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return re.sub(r"[^a-z0-9]+", "-", s.translate(t).lower()).strip("-") or "x"


def front(text: str) -> tuple[dict, str]:
    meta = {}
    if text.startswith("---\n"):
        end = text.index("\n---", 3)
        for line in text[4:end].splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[end + 4:]
    return meta, text


# ------------------------------------------------------------------ handouty HTML → czysty HTML
class Clean(HTMLParser):
    KEEP = {"h1", "h2", "h3", "h4", "p", "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tr",
            "td", "th", "strong", "b", "em", "i", "br", "hr", "small"}
    DROP = {"script", "style", "svg", "nav", "button", "footer", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in self.KEEP:
            cls = dict(attrs).get("class", "")
            self.out.append(f'<{tag}{" class=" + chr(34) + esc(cls) + chr(34) if cls in ("cue", "note", "intro", "couplet") else ""}>')

    def handle_endtag(self, tag):
        if tag in self.DROP:
            self.skip = max(0, self.skip - 1)
            return
        if not self.skip and tag in self.KEEP and tag != "br":
            self.out.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        if not self.skip and tag in ("br", "hr"):
            self.out.append(f"<{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(esc(data))


def handout(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"data:[^\"')]+", "", raw)
    c = Clean()
    c.feed(raw)
    body = "".join(c.out)
    body = re.sub(r"<(p|h\d|li|td|th)>\s*</\1>", "", body)
    body = re.sub(r"\s*\n\s*", "\n", body)
    # tytuł handoutu jako h2 w wydaniu (h1 jest zarezerwowane dla rozdziałów)
    body = re.sub(r"<h(\d)>", lambda m: f"<h{min(int(m.group(1)) + 1, 6)}>", body)
    body = re.sub(r"</h(\d)>", lambda m: f"</h{min(int(m.group(1)) + 1, 6)}>", body)
    return f'<div class="handout">{body}</div>'


def docx_md(path: Path) -> str:
    """Prosty konwerter .docx → Markdown (nagłówki, listy, tabele, pogrubienia)."""
    import docx
    from docx.oxml.ns import qn
    d = docx.Document(str(path))
    out = []
    pstyles = {p._p: p for p in d.paragraphs}
    for el in d.element.body:
        if el.tag == qn("w:p"):
            p = pstyles.get(el)
            if p is None or not p.text.strip():
                continue
            st = p.style.name
            runs = [r for r in p.runs if r.text.strip()]
            all_bold = runs and all(r.bold for r in runs)
            pieces = []
            for r in p.runs:
                t = r.text
                if r.bold and not all_bold and t.strip():
                    lead, core, trail = re.match(r"^(\s*)(.*?)(\s*)$", t, re.S).groups()
                    if pieces and pieces[-1].endswith("**") and not lead:
                        pieces[-1] = pieces[-1][:-2] + core + "**" + trail
                        continue
                    t = f"{lead}**{core}**{trail}"
                pieces.append(t)
            txt = re.sub(r"\*\*(\s*)\*\*", r"\1", "".join(pieces)).strip()
            if st.startswith("Heading 1") or re.match(r"^\w{3} \d{1,2}, \d{4} · ", txt):
                continue
            if st.startswith("Heading"):
                out.append(f"\n## {txt}\n")
            elif all_bold and len(txt) < 70:
                out.append(f"\n#### {txt}\n")
            elif "List" in st:
                out.append(f"- {txt}")
            else:
                out.append(f"\n{txt}\n")
        elif el.tag == qn("w:tbl"):
            rows = []
            for tr in el.iter(qn("w:tr")):
                cells = ["".join(t.text or "" for t in tc.iter(qn("w:t"))).replace("|", "/") for tc in tr.iter(qn("w:tc"))]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                n = rows[0].count("|") - 1
                out.append("\n" + rows[0] + "\n|" + "---|" * n + "\n" + "\n".join(rows[1:]) + "\n")
    return "\n".join(out)


# ------------------------------------------------------------------ preprocesor
def preprocess(text: str, base: Path) -> str:
    def inc(m):
        p = (ROOT / m.group(1).strip())
        meta, body = front(p.read_text(encoding="utf-8"))
        body = re.sub(r"^#\s+.*\n", "", body.lstrip(), count=1)            # tytuł rozdziału daje wydanie
        body = re.sub(r"^\w{3} \d{1,2}, \d{4} · .*\n", "", body.lstrip())   # „Oct 5, 2026 · autor”
        return body

    text = re.sub(r"\{\{include:\s*([^}]+)\}\}", inc, text)
    text = re.sub(r"\{\{docx:\s*([^}]+)\}\}", lambda m: docx_md(ROOT / m.group(1).strip()), text)
    text = re.sub(r"\{\{handout:\s*([^}]+)\}\}", lambda m: "\n\n" + handout(ROOT / m.group(1).strip()) + "\n\n", text)

    def img(m):
        parts = [x.strip() for x in m.group(1).split("|")]
        src, cap = parts[0], (parts[1] if len(parts) > 1 else "")
        cls = parts[2] if len(parts) > 2 else ""
        rel = quote("../" + src) if not src.startswith("05-dla-mg/") else quote(src.split("/", 1)[1])
        return (f'\n\n<figure class="fig {esc(cls)}"><img src="{rel}" alt="{esc(cap)}">'
                f'{f"<figcaption>{esc(cap)}</figcaption>" if cap else ""}</figure>\n\n')

    text = re.sub(r"\{\{img:\s*([^}]+)\}\}", img, text)

    # bloki ::: … :::
    out, stack = [], []
    for line in text.split("\n"):
        m = re.match(r"^:::\s*(\w+)?\s*(.*)$", line)
        if m and m.group(1):
            kind, label = m.group(1), m.group(2).strip()
            if kind == "cols":
                out.append('\n<div class="cols" markdown="1">\n<div class="col" markdown="1">\n')
                stack.append("cols")
                continue
            label = label or LABELS.get(kind, "")
            out.append(f'\n<div class="box {kind}" markdown="1">\n')
            if label:
                out.append(f'<p class="box-label">{esc(label)}</p>\n')
            stack.append(kind)
            continue
        if line.strip() == "|||" and stack and stack[-1] == "cols":
            out.append('\n</div>\n<div class="col" markdown="1">\n')
            continue
        if line.strip() == ":::" and stack:
            kind = stack.pop()
            out.append("\n</div>\n</div>\n" if kind == "cols" else "\n</div>\n")
            continue
        # „**Notka MG.** …” poza blokiem → notka
        nm = re.match(r"^\*\*(Notka MG\.|Dla MG\.|Krytycznie\.|Przejście\.|Zostaw ślad\.)\*\*(.*)$", line)
        if nm and not any(k in ("note", "read", "ledger", "secret", "box") for k in stack):
            out.append(f'\n<div class="box note" markdown="1">\n\n{line}\n\n</div>\n')
            continue
        out.append(line)
    text = "\n".join(out)
    # cytaty > → „Do przeczytania”
    return text


def md(text: str) -> str:
    conv = markdown.Markdown(extensions=["extra", "sane_lists", "toc", "nl2br"],
                             extension_configs={"toc": {"permalink": False}})
    h = conv.convert(text)
    h = h.replace("<blockquote>", '<blockquote class="box read"><p class="box-label">Do przeczytania</p>')
    return h


def shrink_images(doc: str) -> str:
    """Do PDF: obrazy zmniejszone do ~200 dpi na szerokość strony (cache w wydanie/.cache)."""
    from urllib.parse import unquote
    try:
        from PIL import Image
    except ImportError:
        return doc
    cache = HERE / ".cache"
    cache.mkdir(exist_ok=True)

    def repl(m):
        src = unquote(m.group(1))
        path = (OUT_DIR / src).resolve()
        if not path.exists() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            return m.group(0)
        key = re.sub(r"[^\w.-]+", "_", str(path.relative_to(CONTENT)))
        st = path.stat()
        out = cache / f"{key}.{int(st.st_mtime)}.{st.st_size}"
        with Image.open(path) as im:
            alpha = im.mode in ("RGBA", "LA", "P") and "transparency" in im.info or im.mode in ("RGBA", "LA")
            out = out.with_suffix(".png" if alpha else ".jpg")
            if not out.exists():
                im = im.convert("RGBA" if alpha else "RGB")
                im.thumbnail((1500, 1500))
                im.save(out, **({"optimize": True} if alpha else {"quality": 82, "optimize": True}))
        return f'src="{out.as_uri()}"'

    return re.sub(r'src="([^"]+)"', repl, doc)


def css_flat() -> str:
    """Podstawia zmienne CSS z :root (WeasyPrint 70 nie rozwija ich w każdej właściwości)."""
    css = (HERE / "wydanie.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*{(.*?)}", css, re.S).group(1)
    vars_ = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", root))
    for _ in range(3):
        css = re.sub(r"var\((--[\w-]+)\)", lambda m: vars_.get(m.group(1), m.group(0)).strip(), css)
    return css


# ------------------------------------------------------------------ składanie
def build():
    chapters = sorted((HERE / "rozdzialy").glob("*.md"))
    parts, toc = [], []
    for f in chapters:
        meta, body = front(f.read_text(encoding="utf-8"))
        typ = meta.get("typ", "rozdzial")
        title = meta.get("tytul", f.stem)
        cid = meta.get("id") or slug(title)
        run = meta.get("stopka", title)
        kicker = meta.get("kicker", "")
        sub = meta.get("podtytul", "")
        if typ == "czesc":
            parts.append(f"""<section class="part">
  <p class="kicker">{esc(kicker)}</p>
  <h1 class="part-title" id="{cid}" data-run="{esc(run)}">{esc(title)}</h1>
  {f'<p class="subtitle">{esc(sub)}</p>' if sub else ''}
  <div class="part-body">{md(preprocess(body, f.parent))}</div>
</section>""")
            toc.append(("part", cid, title, kicker))
            continue
        html_body = md(preprocess(body, f.parent))
        # identyfikatory h2 unikalne w całym dokumencie
        html_body = re.sub(r'<h2 id="([^"]+)"', lambda m: f'<h2 id="{cid}--{m.group(1)}"', html_body)
        html_body = re.sub(r'<h3 id="([^"]+)"', lambda m: f'<h3 id="{cid}--{m.group(1)}"', html_body)
        html_body = re.sub(r'<h4 id="[^"]+"', "<h4", html_body)
        parts.append(f"""<section class="chapter {typ}">
  <header class="chapter-head">
    {f'<p class="kicker">{esc(kicker)}</p>' if kicker else ''}
    <h1 class="chapter-title" id="{cid}" data-run="{esc(run)}">{esc(title)}</h1>
    {f'<p class="subtitle">{sub}</p>' if sub else ''}
  </header>
  {html_body}
</section>""")
        toc.append((typ, cid, title, kicker))

    toc_html = []
    for typ, cid, title, kicker in toc:
        if typ == "czesc":
            toc_html.append(f'<li class="toc-part"><a href="#{cid}"><span>{esc(kicker)} · {esc(title)}</span></a></li>')
        else:
            toc_html.append(f'<li class="toc-ch{" toc-app" if typ == "dodatek" else ""}"><a href="#{cid}"><span>{esc(title)}</span></a></li>')

    cover = (HERE / "okladka.md").read_text(encoding="utf-8")
    cover_meta, cover_body = front(cover)
    doc = f"""<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jednostrzał i sesje zero graczy · Stajnia 97 „Gardens”</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Alfa+Slab+One&family=Courier+Prime:ital,wght@0,400;0,700;1,400&family=EB+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,600&display=swap" media="screen">
<style>
{css_flat()}
</style>
</head>
<body>
<section class="cover">
  <p class="kicker">Fallout: Equestria · Stajnia 97 „Gardens”</p>
  <h1 class="cover-title">Jednostrzał</h1>
  <p class="subtitle">i sesje zero graczy</p>
  <p class="stamp">Tylko dla MG</p>
  <p class="edition">Wydanie zbiorcze · stan na {STAN}</p>
  <h2 class="toc-title">Spis treści</h2>
  <ol class="toc">{''.join(toc_html)}</ol>
  <div class="legend">
    <div class="box read"><p class="box-label">Do przeczytania</p><p>Tekst do przeczytania graczowi.</p></div>
    <div class="box note"><p><strong>Notka MG.</strong> Wskazówki prowadzenia, nie dla graczy.</p></div>
    <div class="box ledger"><p class="box-label">Wpis w księdze</p><p>Wpisy Gunthera (tylko sesja Uriela).</p></div>
    <div class="box secret"><p class="box-label">Sekret MG</p><p>Rzeczy, których gracz nie może zobaczyć.</p></div>
  </div>
  <div class="cover-foot">{md(cover_body)}</div>
</section>
{''.join(parts)}
</body>
</html>
"""
    out_html = OUT_DIR / f"{OUT_NAME}.html"
    out_html.write_text(doc, encoding="utf-8")
    print("✔ HTML:", out_html.relative_to(ROOT))

    if "--bez-pdf" in sys.argv:
        return
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration
    fc = FontConfiguration()
    fonts = (HERE / "fonts.css").read_text(encoding="utf-8").replace("url('fonts/", f"url('{(HERE / 'fonts').as_uri()}/")
    out_pdf = OUT_DIR / f"{OUT_NAME}.pdf"
    doc = shrink_images(doc)
    HTML(string=doc, base_url=str(OUT_DIR) + "/").write_pdf(out_pdf, stylesheets=[CSS(string=fonts, font_config=fc)], font_config=fc)
    print("✔ PDF :", out_pdf.relative_to(ROOT), f"({out_pdf.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
