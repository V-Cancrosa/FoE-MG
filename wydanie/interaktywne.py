"""Interaktywna wersja wydania (strona główna serwisu).

Bierze HTML wydania, oznacza w tekście nazwy z leksykonu (BN-y, postacie, umiejętności,
atrybuty) i dokłada kartki po najechaniu, panel leksykonu i bramkę „tylko dla MG”.
Wynik: wydanie/interaktywny.html — tools/build.py kopiuje go jako index.html w katalogu głównym.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP_TAGS = {"a", "script", "style", "title", "h1", "figcaption", "code"}


def load_lexicon() -> list[dict]:
    return json.loads((HERE / "leksykon.json").read_text(encoding="utf-8"))["wpisy"]


def build_regex(entries: list[dict]):
    parts, ids = [], []
    for e in entries:
        for p in e["wzorce"]:
            ids.append(e["id"])
            parts.append(f"(?P<g{len(ids) - 1}>\\b(?:{p}))")
    # dłuższe wzorce najpierw, żeby „Rick Scrapper” wygrało z „Rick”
    order = sorted(range(len(parts)), key=lambda i: -len(parts[i]))
    rx = re.compile("|".join(parts[i] for i in order))
    return rx, ids


def mark_terms(doc: str, entries: list[dict]) -> str:
    rx, ids = build_regex(entries)
    out, stack = [], []
    for tok in re.split(r"(<[^>]+>)", doc):
        if tok.startswith("<"):
            m = re.match(r"<(/?)([a-zA-Z0-9]+)", tok)
            if m:
                name = m.group(2).lower()
                if name in SKIP_TAGS and not tok.endswith("/>"):
                    if m.group(1):
                        if stack and stack[-1] == name:
                            stack.pop()
                    else:
                        stack.append(name)
            out.append(tok)
            continue
        if stack or not tok.strip():
            out.append(tok)
            continue

        def repl(m):
            idx = int(m.lastgroup[1:])
            return f'<span class="lx" data-lx="{ids[idx]}">{m.group(0)}</span>'
        out.append(rx.sub(repl, tok))
    return "".join(out)


CSS = r"""
@media screen {
  .lx { border-bottom: 1px dotted #a4502a; cursor: help; }
  .lx:hover { background: #f6e7d3; }
  .lx-card { position: fixed; z-index: 1000; width: min(360px, calc(100vw - 24px)); background: #fffdf8;
    border: 1px solid #c9b28a; border-top: 3px solid #a4502a; box-shadow: 0 8px 28px rgba(0,0,0,.22);
    padding: 12px 14px; font: 15px/1.38 "EB Garamond", Georgia, serif; color: #1f1a16; display: none; }
  .lx-card.on { display: block; }
  .lx-card .t { font: 7.5pt "Courier Prime", monospace; letter-spacing: .2em; text-transform: uppercase; color: #9a2a22; margin: 0 0 2px; }
  .lx-card h3 { font: 400 19px "Alfa Slab One", Georgia, serif; color: #5a3a22; margin: 0 0 6px; }
  .lx-card img { float: right; max-width: 88px; max-height: 110px; margin: 0 0 6px 8px; border: 1px solid #e6dcc8; }
  .lx-card p { margin: 0 0 5px; text-align: left; }
  .lx-card b { font-weight: 600; color: #5a3a22; }
  .lx-card .sek { background: #fbefe9; border: 1px dashed #9a2a22; padding: 4px 6px; margin-top: 6px; }
  .lx-card .x { position: absolute; right: 6px; top: 2px; border: 0; background: none; font-size: 20px; cursor: pointer; color: #8a8178; display: none; }
  .lx-card.pinned .x { display: block; }
  .ix-bar { position: sticky; top: 0; z-index: 900; display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
    background: #2b211b; color: #efe6d4; padding: 8px 14px; margin: -48px -56px 24px; font: 13px "Courier Prime", monospace; }
  .ix-bar a, .ix-bar button { color: #efe6d4; background: none; border: 1px solid #6b5543; padding: 4px 10px; cursor: pointer; font: inherit; text-decoration: none; }
  .ix-bar a:hover, .ix-bar button:hover { background: #4a3a2e; }
  .ix-bar .sp { flex: 1; }
  .ix-panel { position: fixed; right: 0; top: 0; bottom: 0; width: min(380px, 100vw); z-index: 950; background: #fffdf8;
    border-left: 1px solid #c9b28a; box-shadow: -8px 0 28px rgba(0,0,0,.18); overflow: auto; padding: 14px; transform: translateX(100%); transition: transform .2s; }
  .ix-panel.on { transform: none; }
  .ix-panel input { width: 100%; padding: 6px 8px; font: 15px "EB Garamond", serif; border: 1px solid #c9b28a; margin-bottom: 8px; box-sizing: border-box; }
  .ix-panel .grp { font: 7.5pt "Courier Prime", monospace; letter-spacing: .2em; text-transform: uppercase; color: #9a2a22; margin: 12px 0 4px; }
  .ix-panel .it { padding: 6px 4px; border-bottom: 1px dotted #c9b28a; cursor: pointer; }
  .ix-panel .it:hover { background: #f6e7d3; }
  .ix-panel .it small { display: block; color: #8a8178; }
  .ix-gate { position: fixed; inset: 0; z-index: 2000; background: #1f1a16; color: #efe6d4; display: flex; align-items: center; justify-content: center; text-align: center; padding: 24px; }
  .ix-gate h2 { font: 400 34px "Alfa Slab One", serif; color: #efe6d4; margin: 0 0 10px; }
  .ix-gate p { max-width: 420px; margin: 0 auto 16px; text-align: center; }
  .ix-gate button, .ix-gate a { font: 14px "Courier Prime", monospace; padding: 8px 14px; margin: 4px; border: 1px solid #a4502a; background: #a4502a; color: #fff; cursor: pointer; text-decoration: none; display: inline-block; }
  .ix-gate a { background: none; color: #efe6d4; }
  html.mg-ok .ix-gate { display: none; }
  @media (max-width: 700px) { .ix-bar { margin: -20px -16px 16px; } }
}
@media print { .ix-bar, .ix-panel, .lx-card, .ix-gate { display: none !important; } }
"""

JS = r"""
(function(){
  var LX = JSON.parse(document.getElementById('lx-data').textContent), byId = {};
  LX.forEach(function(e){ byId[e.id] = e; });
  try { if (localStorage.getItem('mg-ok') === '1') document.documentElement.classList.add('mg-ok'); } catch(e) {}
  var ok = document.querySelector('[data-gate-ok]');
  if (ok) ok.addEventListener('click', function(){ try { localStorage.setItem('mg-ok','1'); } catch(e) {} document.documentElement.classList.add('mg-ok'); });

  var card = document.createElement('div'); card.className = 'lx-card'; document.body.appendChild(card);
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function fill(e){
    var h = '<button class="x" aria-label="Zamknij">×</button><p class="t">' + esc(e.typ) + '</p>';
    if (e.obraz) h += '<img src="content/' + encodeURI(e.obraz) + '" alt="">';
    h += '<h3>' + esc(e.nazwa) + '</h3>';
    if (e.kim) h += '<p>' + esc(e.kim) + '</p>';
    if (e.wyglad) h += '<p><b>Wygląd.</b> ' + esc(e.wyglad) + '</p>';
    if (e.charakter) h += '<p><b>Charakter.</b> ' + esc(e.charakter) + '</p>';
    if (e.gdzie) h += '<p><b>Gdzie.</b> ' + esc(e.gdzie) + '</p>';
    if (e.rzuty) h += '<p><b>' + (/^(Umiejętność|Atrybut|Zasada)/.test(e.typ) ? 'Przy stole.' : 'Mechanika.') + '</b> ' + esc(e.rzuty) + '</p>';
    if (e.sekret) h += '<p class="sek"><b>Sekret MG.</b> ' + esc(e.sekret) + '</p>';
    card.innerHTML = h;
    card.querySelector('.x').onclick = function(){ card.className = 'lx-card'; };
  }
  function place(x, y){
    card.classList.add('on');
    var w = card.offsetWidth, hh = card.offsetHeight, vw = innerWidth, vh = innerHeight;
    var left = Math.min(Math.max(8, x + 14), vw - w - 8), top = y + 18;
    if (top + hh > vh - 8) top = Math.max(8, y - hh - 12);
    card.style.left = left + 'px'; card.style.top = top + 'px';
  }
  var pinned = false;
  document.addEventListener('mouseover', function(ev){
    var t = ev.target.closest && ev.target.closest('.lx'); if (!t || pinned) return;
    var e = byId[t.dataset.lx]; if (!e) return; fill(e);
    var r = t.getBoundingClientRect(); place(r.left, r.bottom - 10);
  });
  document.addEventListener('mouseout', function(ev){
    var t = ev.target.closest && ev.target.closest('.lx'); if (t && !pinned) card.className = 'lx-card';
  });
  document.addEventListener('click', function(ev){
    var t = ev.target.closest && ev.target.closest('.lx');
    if (t) { var e = byId[t.dataset.lx]; fill(e); pinned = true; card.className = 'lx-card pinned';
      var r = t.getBoundingClientRect(); place(r.left, r.bottom - 10); ev.preventDefault(); return; }
    if (!card.contains(ev.target) && !ev.target.closest('.ix-panel')) { pinned = false; card.className = 'lx-card'; }
  });
  document.addEventListener('keydown', function(ev){ if (ev.key === 'Escape') { pinned = false; card.className = 'lx-card'; panel.classList.remove('on'); } });

  var panel = document.querySelector('.ix-panel'), list = panel.querySelector('.list'), q = panel.querySelector('input');
  function render(){
    var s = q.value.toLowerCase(), groups = {}, order = [];
    LX.forEach(function(e){
      var txt = (e.nazwa + ' ' + (e.kim||'') + ' ' + (e.typ||'')).toLowerCase();
      if (s && txt.indexOf(s) < 0) return;
      var g = e.typ.split(' · ')[0] === 'BN' ? e.typ : e.typ.split(' · ')[0];
      if (!groups[g]) { groups[g] = []; order.push(g); } groups[g].push(e);
    });
    list.innerHTML = order.map(function(g){ return '<p class="grp">' + esc(g) + '</p>' + groups[g].map(function(e){
      return '<div class="it" data-id="' + e.id + '"><b>' + esc(e.nazwa) + '</b><small>' + esc((e.kim||'').slice(0,90)) + '</small></div>'; }).join(''); }).join('');
  }
  q.addEventListener('input', render); render();
  list.addEventListener('click', function(ev){
    var it = ev.target.closest('.it'); if (!it) return; fill(byId[it.dataset.id]); pinned = true;
    card.className = 'lx-card pinned'; var r = it.getBoundingClientRect(); place(Math.max(8, r.left - 380), r.top);
  });
  document.querySelectorAll('[data-panel]').forEach(function(b){ b.onclick = function(){ panel.classList.toggle('on'); if (panel.classList.contains('on')) q.focus(); }; });
})();
"""


def make_interactive(doc: str, pdf_name: str) -> str:
    entries = load_lexicon()
    doc = doc.replace('src="../', 'src="content/').replace('href="../', 'href="content/')
    head, sep, body = doc.partition("<body>")
    body = mark_terms(body, entries)
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    bar = f"""<div class="ix-gate"><div><h2>Tylko dla MG</h2>
<p>To jest dokument mistrza gry z sekretami jednostrzału i sesji zero. Jeśli grasz w tej kampanii, zawróć.</p>
<a href="biblioteka.html">Do biblioteki materiałów</a><button data-gate-ok>Jestem MG — pokaż</button></div></div>
<nav class="ix-bar"><strong>Stajnia 97 · MG</strong><span class="sp"></span>
<button data-panel>BN-y i ściąga (najedź albo kliknij nazwę w tekście)</button>
<a href="content/05-dla-mg/{pdf_name}.pdf">PDF</a><a href="biblioteka.html">Biblioteka</a></nav>
<aside class="ix-panel"><input type="search" placeholder="Szukaj: imię, umiejętność, atrybut…"><div class="list"></div></aside>"""
    head = head.replace("</head>", f"<style>{CSS}</style>\n</head>")
    return head + sep + "\n" + bar + body.replace(
        "</body>", f'<script type="application/json" id="lx-data">{data}</script>\n<script>{JS}</script>\n</body>')
