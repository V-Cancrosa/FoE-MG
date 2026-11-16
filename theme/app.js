// FoE-MG — interakcje: motyw, menu, filtry, wyszukiwarka, lightbox
(function () {
  const root = document.body.dataset.root || "";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  // motyw
  $$("[data-theme-toggle]").forEach((b) => b.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
  }));

  // menu mobilne
  const menuBtn = $("[data-menu]"), nav = $("[data-nav]");
  if (menuBtn && nav) menuBtn.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    menuBtn.setAttribute("aria-expanded", open);
  });

  // bramka spoilerów (strefa MG) — zapamiętana w przeglądarce
  const MG_KEY = "mg-ok";
  const mgOk = () => { try { return localStorage.getItem(MG_KEY) === "1"; } catch (e) { return false; } };
  const gate = $("[data-gate]");
  if (gate && !mgOk()) {
    gate.hidden = false; document.body.classList.add("gated");
    $("[data-gate-ok]", gate).addEventListener("click", () => {
      try { localStorage.setItem(MG_KEY, "1"); } catch (e) {}
      gate.hidden = true; document.body.classList.remove("gated");
    });
  }

  // filtry na stronie "Wszystko"
  const grid = $("[data-filter-grid]");
  if (grid) {
    const txt = $("[data-filter-text]"), col = $("[data-filter-col]"), kind = $("[data-filter-kind]");
    const count = $("[data-count]"), empty = $("[data-filter-empty]");
    const spoilerBox = $("[data-filter-spoiler]");
    const spoilerCols = ($("[data-filters]").dataset.spoilerCols || "").split(" ").filter(Boolean);
    if (spoilerBox) spoilerBox.checked = mgOk();
    const params = new URLSearchParams(location.search);
    if (params.get("q")) txt.value = params.get("q");
    if (params.get("etap")) col.value = params.get("etap");
    if (params.get("typ")) kind.value = params.get("typ");
    const apply = () => {
      const q = norm(txt.value), c = col.value, k = kind.value;
      const showMg = (spoilerBox && spoilerBox.checked) || spoilerCols.includes(c);
      let n = 0;
      $$(".card", grid).forEach((el) => {
        const ok = (!q || norm(el.dataset.text).includes(q)) && (!c || el.dataset.col === c) && (!k || el.dataset.kind === k) &&
          (showMg || !spoilerCols.includes(el.dataset.col));
        el.hidden = !ok; if (ok) n++;
      });
      count.textContent = n; empty.hidden = n > 0;
    };
    [txt, col, kind, spoilerBox].filter(Boolean).forEach((el) => el.addEventListener("input", apply));
    apply();
  }

  // lightbox
  $$("[data-lightbox]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const fig = document.createElement("figure");
    fig.className = "lightbox";
    fig.innerHTML = `<img src="${a.href}" alt=""><figcaption></figcaption>`;
    fig.querySelector("figcaption").textContent = a.title || "";
    fig.addEventListener("click", () => fig.remove());
    document.addEventListener("keydown", function esc(ev) { if (ev.key === "Escape") { fig.remove(); document.removeEventListener("keydown", esc); } });
    document.body.appendChild(fig);
  }));

  // wyszukiwarka globalna
  const modal = $("[data-search-modal]"), input = $("[data-search-input]"), list = $("[data-search-results]");
  let index = null, sel = 0, results = [];
  function norm(s) { return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l"); }
  function escHtml(s) { return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  async function load() {
    if (index) return index;
    try { index = await (await fetch(root + "search.json")).json(); } catch (e) { index = []; }
    index.forEach((d) => { d._t = norm(d.t); d._all = norm([d.t, d.s, d.c, (d.g || []).join(" "), d.p].join(" ")); });
    return index;
  }
  function open() { modal.hidden = false; input.focus(); input.select(); load().then(render); }
  function close() { modal.hidden = true; }
  function render() {
    const q = norm(input.value.trim());
    const words = q.split(/\s+/).filter(Boolean);
    results = !words.length ? [] : index
      .filter((d) => (!d.x || mgOk()) && words.every((w) => d._all.includes(w)))
      .map((d) => ({ d, score: words.reduce((s, w) => s + (d._t.includes(w) ? 10 : 1), 0) }))
      .sort((a, b) => b.score - a.score).slice(0, 30).map((x) => x.d);
    sel = 0;
    list.innerHTML = results.map((d, i) => {
      const ext = d.k !== "doc" && d.k !== "image" ? ' target="_blank" rel="noopener"' : "";
      return `<li class="${i === sel ? "sel" : ""}"><a href="${root}${encodeURI(d.h)}"${ext}>${escHtml(d.t)}<small>${escHtml(d.c)} · ${escHtml(d.d || "")} — ${escHtml((d.s || "").slice(0, 140))}</small></a></li>`;
    }).join("") || (words.length ? '<li class="muted" style="padding:10px 12px">Brak wyników.</li>' : "");
  }
  if (modal) {
    $$("[data-search-open]").forEach((b) => b.addEventListener("click", open));
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    input.addEventListener("input", render);
    input.addEventListener("keydown", (e) => {
      const items = $$("li", list);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!items.length) return;
        items[sel] && items[sel].classList.remove("sel");
        sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items[sel].classList.add("sel"); items[sel].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        const a = items[sel] && $("a", items[sel]); if (a) a.click();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.hidden) close();
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
      if (!typing && (e.key === "/" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k"))) { e.preventDefault(); open(); }
    });
  }
})();
