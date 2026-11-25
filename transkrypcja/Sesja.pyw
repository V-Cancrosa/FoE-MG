"""Okno do nagrywania i transkrypcji sesji. Uruchamiaj skrótem „Sesja” (bez konsoli)."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

TU = Path(__file__).resolve().parent
sys.path.insert(0, str(TU))
import nagrywaj as N  # noqa: E402

WINDOWS = sys.platform == "win32"
BEZ_OKNA = 0x08000000 if WINDOWS else 0  # CREATE_NO_WINDOW
BOT = "Bot Discord — każdy gracz osobno"
LOOPBACK_DOM = "Wszystko ze słuchawek (domyślne wyjście)"
MODELE = ["auto", "large-v3", "large-v3-turbo", "medium", "small"]
TOKEN = TU / "bot" / "token.txt"


def python_konsolowy() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def otworz(sciezka: Path):
    if WINDOWS:
        os.startfile(sciezka)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(sciezka)])


def parsuj_postacie(tekst: str) -> dict:
    """Linie „nick = postać” → słownik."""
    out = {}
    for l in tekst.splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k, v = l.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


class Okno:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Sesja — nagrywanie i transkrypcja")
        root.minsize(620, 640)
        self.cfg = N.ustawienia()
        self.q: queue.Queue = queue.Queue()
        self.nagr: N.Nagrywanie | None = None      # lokalne nagrywanie
        self.zapas: N.Nagrywanie | None = None     # mikrofon zapasowy przy bocie
        self.bot: subprocess.Popen | None = None
        self.bot_gotowy = False
        self.bot_katalog: Path | None = None
        self.bot_poziomy: dict = {}
        self.t0 = 0.0
        self.transkr: subprocess.Popen | None = None
        self.sa = None
        self.wejscia, self.wyjscia = [], []
        try:
            self.sa = N.system_audio()
            self.wejscia, self.wyjscia = self.sa.nazwy()
        except Exception as e:  # brak PyAudioWPatch/PortAudio — bot dalej działa
            self.q.put(("log", f"Dźwięk lokalny niedostępny: {e}"))
        self.zbuduj()
        self.root.protocol("WM_DELETE_WINDOW", self.zamknij)
        self.root.after(200, self.petla)

    # ------------------------------------------------------------ układ
    def zbuduj(self):
        pad = {"padx": 8, "pady": 4}
        f = ttk.LabelFrame(self.root, text="Źródła")
        f.pack(fill="x", **pad)
        ttk.Label(f, text="Mój mikrofon:").grid(row=0, column=0, sticky="w", **pad)
        self.v_mik = tk.StringVar(value=self.cfg.get("mikrofon") or "(domyślny)")
        ttk.Combobox(f, textvariable=self.v_mik, state="readonly", width=52,
                     values=["(domyślny)"] + self.wejscia).grid(row=0, column=1, sticky="we", **pad)
        ttk.Label(f, text="Gracze (Discord):").grid(row=1, column=0, sticky="w", **pad)
        self.opcje_discord = {LOOPBACK_DOM: ""}
        for n in self.wyjscia:
            self.opcje_discord[f"Wyjście: {n}"] = n
        for n in self.wejscia:
            self.opcje_discord[f"Wejście: {n}"] = f"wejscie:{n}"
        self.opcje_discord[BOT] = "bot"
        obecny = next((k for k, v in self.opcje_discord.items() if v == self.cfg.get("discord", "")), LOOPBACK_DOM)
        self.v_disc = tk.StringVar(value=obecny)
        cb = ttk.Combobox(f, textvariable=self.v_disc, state="readonly", width=52, values=list(self.opcje_discord))
        cb.grid(row=1, column=1, sticky="we", **pad)
        cb.bind("<<ComboboxSelected>>", lambda e: self.tryb_zmieniony())
        f.columnconfigure(1, weight=1)

        # bot
        self.f_bot = ttk.LabelFrame(self.root, text="Bot Discord")
        self.f_bot.pack(fill="x", **pad)
        ttk.Label(self.f_bot, text="Token:").grid(row=0, column=0, sticky="w", **pad)
        self.v_token = tk.StringVar(value=TOKEN.read_text(encoding="utf-8").strip() if TOKEN.exists() else "")
        ttk.Entry(self.f_bot, textvariable=self.v_token, show="•", width=40).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(self.f_bot, text="Zapisz token", command=self.zapisz_token).grid(row=0, column=2, **pad)
        ttk.Label(self.f_bot, text="MG na Discordzie:").grid(row=1, column=0, sticky="w", **pad)
        self.v_mg = tk.StringVar(value=self.cfg.get("bot", {}).get("mg", ""))
        ttk.Entry(self.f_bot, textvariable=self.v_mg, width=40).grid(row=1, column=1, sticky="we", **pad)
        self.b_bot = ttk.Button(self.f_bot, text="Uruchom bota", command=self.przelacz_bota)
        self.b_bot.grid(row=1, column=2, **pad)
        ttk.Label(self.f_bot, text="Postacie\n(nick = postać):").grid(row=2, column=0, sticky="nw", **pad)
        self.t_post = tk.Text(self.f_bot, height=4, width=40)
        self.t_post.grid(row=2, column=1, columnspan=2, sticky="we", **pad)
        self.t_post.insert("1.0", "\n".join(f"{k} = {v}" for k, v in self.cfg.get("postacie", {}).items())
                           or "# przykład:\n# zychu = Uriel (zychu)")
        self.v_zapas = tk.BooleanVar(value=self.cfg.get("bot", {}).get("zapas", True))
        ttk.Checkbutton(self.f_bot, text="Nagrywaj też mój mikrofon lokalnie (zapas)",
                        variable=self.v_zapas).grid(row=3, column=1, sticky="w", **pad)
        self.l_bot = ttk.Label(self.f_bot, text="Bot: wyłączony", foreground="#9a2a22")
        self.l_bot.grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        self.f_bot.columnconfigure(1, weight=1)

        # nagrywanie
        f = ttk.LabelFrame(self.root, text="Nagrywanie")
        f.pack(fill="x", **pad)
        self.b_nagr = ttk.Button(f, text="● Start", command=self.przelacz_nagrywanie, width=14)
        self.b_nagr.grid(row=0, column=0, **pad)
        self.l_czas = ttk.Label(f, text="00:00:00", font=("Consolas", 16))
        self.l_czas.grid(row=0, column=1, sticky="w", **pad)
        ttk.Button(f, text="Otwórz folder nagrań", command=self.otworz_folder).grid(row=0, column=2, **pad)
        self.c_poz = tk.Canvas(f, height=60, background="#f3f0ea", highlightthickness=0)
        self.c_poz.grid(row=1, column=0, columnspan=3, sticky="we", **pad)
        f.columnconfigure(1, weight=1)

        # transkrypcja
        f = ttk.LabelFrame(self.root, text="Transkrypcja")
        f.pack(fill="x", **pad)
        ttk.Label(f, text="Model:").grid(row=0, column=0, **pad)
        self.v_model = tk.StringVar(value=self.cfg.get("model", "auto"))
        ttk.Combobox(f, textvariable=self.v_model, state="readonly", values=MODELE, width=16).grid(row=0, column=1, **pad)
        self.b_tr = ttk.Button(f, text="Transkrybuj ostatnią sesję", command=self.transkrybuj)
        self.b_tr.grid(row=0, column=2, **pad)
        ttk.Button(f, text="Otwórz transkrypcję", command=self.otworz_transkrypcje).grid(row=0, column=3, **pad)
        self.pb = ttk.Progressbar(f, maximum=1.0)
        self.pb.grid(row=1, column=0, columnspan=4, sticky="we", **pad)
        self.l_tr = ttk.Label(f, text="")
        self.l_tr.grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        f.columnconfigure(2, weight=1)

        self.log_w = scrolledtext.ScrolledText(self.root, height=10, state="disabled", font=("Consolas", 9))
        self.log_w.pack(fill="both", expand=True, **pad)
        self.tryb_zmieniony()

    # ------------------------------------------------------------ pomocnicze
    def log(self, t: str):
        self.log_w.configure(state="normal")
        self.log_w.insert("end", time.strftime("%H:%M:%S ") + t + "\n")
        self.log_w.see("end")
        self.log_w.configure(state="disabled")

    def tryb_bot(self) -> bool:
        return self.opcje_discord.get(self.v_disc.get()) == "bot"

    def tryb_zmieniony(self):
        stan = "normal" if self.tryb_bot() else "disabled"
        for w in self.f_bot.winfo_children():
            try:
                w.configure(state=stan)
            except tk.TclError:
                pass
        self.zapisz_ustawienia()

    def zapisz_ustawienia(self):
        mik = self.v_mik.get()
        self.cfg.update(mikrofon="" if mik == "(domyślny)" else mik,
                        discord=self.opcje_discord.get(self.v_disc.get(), ""),
                        model=self.v_model.get(),
                        postacie=parsuj_postacie(self.t_post.get("1.0", "end")))
        self.cfg["bot"] = {"mg": self.v_mg.get().strip(), "zapas": bool(self.v_zapas.get())}
        N.zapisz_ustawienia(self.cfg)

    def zapisz_token(self):
        t = self.v_token.get().strip()
        TOKEN.parent.mkdir(exist_ok=True)
        TOKEN.write_text(t + "\n", encoding="utf-8")
        self.log("Token zapisany w bot/token.txt (plik jest poza gitem).")

    # ------------------------------------------------------------ nagrywanie lokalne
    def przelacz_nagrywanie(self):
        self.zapisz_ustawienia()
        if self.nagrywa():
            self.zatrzymaj()
        elif self.tryb_bot():
            self.start_bot_nagrania()
        else:
            self.start_lokalne()

    def nagrywa(self) -> bool:
        return self.nagr is not None or self.bot_katalog is not None

    def start_lokalne(self):
        if not self.sa:
            messagebox.showerror("Brak dźwięku", "Nie mogę otworzyć urządzeń audio (patrz log).")
            return
        try:
            self.nagr = N.Nagrywanie(self.sa, self.cfg.get("mikrofon", ""), self.cfg.get("discord", ""))
            k = N.nowy_katalog(self.cfg)
            self.nagr.start(k)
        except (Exception, SystemExit) as e:
            self.nagr = None
            messagebox.showerror("Nie mogę nagrywać", str(e))
            return
        self.t0 = self.nagr.t0
        for et, _, d in self.nagr.zrodla:
            self.log(f"● {et} ← {d['name']}")
        self.log(f"Nagrywam do {k}")
        self.b_nagr.configure(text="■ Stop")

    def zatrzymaj(self):
        self.b_nagr.configure(state="disabled", text="Zamykam…")
        if self.bot_katalog is not None:
            self.bot_pisz("stop")
            return  # dalej w obsłudze zdarzenia „stop” od bota
        n, self.nagr = self.nagr, None
        threading.Thread(target=self._zamknij_nagranie, args=(n,), daemon=True).start()

    def _zamknij_nagranie(self, n: N.Nagrywanie):
        n.stop(log=lambda t: self.q.put(("log", t)))
        self.q.put(("log", f"Nagranie zapisane: {n.katalog}"))
        self.q.put(("koniec_nagrania", None))

    # ------------------------------------------------------------ bot
    def przelacz_bota(self):
        if self.bot and self.bot.poll() is None:
            self.bot_pisz("koniec")
            return
        self.uruchom_bota()

    def uruchom_bota(self) -> bool:
        if self.bot and self.bot.poll() is None:
            return True
        node = shutil.which("node")
        if not node:
            messagebox.showerror("Brak Node.js", "Tryb bota potrzebuje Node.js (nodejs.org, wersja LTS). "
                                 "Zainstaluj i uruchom instaluj.bat jeszcze raz.")
            return False
        if not (TU / "bot" / "node_modules").exists():
            messagebox.showerror("Bot nie zainstalowany", "Uruchom instaluj.bat (zainstaluje bota).")
            return False
        if self.v_token.get().strip():
            self.zapisz_token()
        self.zapisz_ustawienia()
        self.bot = subprocess.Popen(
            [node, str(TU / "bot" / "nagrywacz.mjs"), "--folder", str(N.folder_nagran(self.cfg))],
            cwd=TU / "bot", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=BEZ_OKNA)
        threading.Thread(target=self._czytaj_bota, args=(self.bot,), daemon=True).start()
        self.l_bot.configure(text="Bot: łączę się…")
        self.b_bot.configure(text="Wyłącz bota")
        return True

    def _czytaj_bota(self, p: subprocess.Popen):
        for linia in p.stdout:
            linia = linia.strip()
            if not linia:
                continue
            try:
                self.q.put(("bot", json.loads(linia)))
            except json.JSONDecodeError:
                self.q.put(("log", f"[bot] {linia}"))
        self.q.put(("bot", {"zdarzenie": "wyjscie", "kod": p.wait()}))

    def bot_pisz(self, komenda: str):
        if self.bot and self.bot.poll() is None:
            try:
                self.bot.stdin.write(komenda + "\n")
                self.bot.stdin.flush()
            except OSError:
                pass

    def start_bot_nagrania(self):
        if not self.uruchom_bota():
            return
        if self.bot_gotowy:
            self.bot_pisz("start")
        else:
            self._start_po_gotowosci = True
            self.log("Czekam, aż bot się połączy…")

    def zdarzenie_bota(self, z: dict):
        if "log" in z and "zdarzenie" not in z:
            self.log(f"[bot] {z['log']}")
        if "poziomy" in z:
            self.bot_poziomy = z["poziomy"]
        ev = z.get("zdarzenie")
        if ev == "gotowy":
            self.bot_gotowy = True
            self.l_bot.configure(text=f"Bot: {z['bot']} · serwery: {', '.join(z['serwery']) or 'brak — zaproś bota'}",
                                 foreground="#2a6a2a")
            if getattr(self, "_start_po_gotowosci", False):
                self._start_po_gotowosci = False
                self.bot_pisz("start")
        elif ev == "start":
            self.bot_katalog = Path(z["katalog"])
            self.t0 = time.time()
            self.b_nagr.configure(text="■ Stop", state="normal")
            self.log(f"Bot nagrywa „{z['kanal']}” do {self.bot_katalog}")
            if self.v_zapas.get() and self.sa:
                try:
                    self.zapas = N.Nagrywanie(self.sa, self.cfg.get("mikrofon", ""), None)
                    zk = self.bot_katalog / "zapas"
                    zk.mkdir(exist_ok=True)
                    self.zapas.start(zk, "zapas")
                    self.log("Zapasowy mikrofon lokalny: włączony.")
                except (Exception, SystemExit) as e:
                    self.zapas = None
                    self.log(f"Zapasowy mikrofon nie ruszył: {e}")
        elif ev == "stop":
            k, self.bot_katalog = Path(z["katalog"]), None
            zapas, self.zapas = self.zapas, None
            threading.Thread(target=self._po_bocie, args=(k, zapas), daemon=True).start()
        elif ev == "blad":
            self.log(f"[bot] {z.get('log')}")
            self.l_bot.configure(text="Bot: błąd (patrz log)", foreground="#9a2a22")
        elif ev == "wyjscie":
            self.bot_gotowy = False
            self.l_bot.configure(text="Bot: wyłączony", foreground="#9a2a22")
            self.b_bot.configure(text="Uruchom bota")
            if self.bot_katalog is not None:
                self.bot_katalog = None
                self.q.put(("koniec_nagrania", None))

    def _po_bocie(self, k: Path, zapas):
        if zapas:
            zapas.stop(log=lambda t: self.q.put(("log", t)))
        N.kompresuj(k, log=lambda t: self.q.put(("log", t)))
        self.q.put(("log", f"Nagranie zapisane: {k}"))
        self.q.put(("koniec_nagrania", None))

    # ------------------------------------------------------------ transkrypcja
    def transkrybuj(self):
        if self.transkr and self.transkr.poll() is None:
            return
        if self.nagrywa():
            messagebox.showinfo("Nagrywanie trwa", "Najpierw zatrzymaj nagrywanie.")
            return
        self.zapisz_ustawienia()
        cmd = [python_konsolowy(), "-u", str(TU / "transkrybuj.py"), "--postep-json", "--model", self.v_model.get()]
        self.transkr = subprocess.Popen(cmd, cwd=TU, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        encoding="utf-8", errors="replace", bufsize=1, creationflags=BEZ_OKNA,
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.b_tr.configure(state="disabled")
        self.pb["value"] = 0
        self.tr_plik = (1, 1)
        threading.Thread(target=self._czytaj_transkr, args=(self.transkr,), daemon=True).start()

    def _czytaj_transkr(self, p):
        for linia in p.stdout:
            linia = linia.rstrip()
            if linia.startswith("@@"):
                try:
                    self.q.put(("postep", json.loads(linia[2:])))
                    continue
                except json.JSONDecodeError:
                    pass
            if linia:
                self.q.put(("log", linia))
        self.q.put(("koniec_transkr", p.wait()))

    def postep(self, d: dict):
        if "plik_nr" in d:
            self.tr_plik = (d["plik_nr"], d["plikow"])
        nr, ile_plikow = self.tr_plik
        if "ile" in d:
            self.pb["value"] = (nr - 1 + d["ile"]) / ile_plikow
            self.l_tr.configure(text=f"Ścieżka {nr}/{ile_plikow}: {d.get('mowca', '')} — {d['ile']:.0%}"
                                     + (f", zostało ok. {d['zostalo']}" if d.get("zostalo") else ""))
        if "gotowe" in d:
            self.pb["value"] = 1.0
            self.ostatnia_transkrypcja = Path(d["gotowe"])
            self.l_tr.configure(text=f"Gotowe: {self.ostatnia_transkrypcja}")

    def otworz_transkrypcje(self):
        p = getattr(self, "ostatnia_transkrypcja", None)
        if not p:
            try:
                import transkrybuj as T
                p = T.ostatnia_sesja() / "transkrypcja.md"
            except SystemExit:
                p = None
        if p and Path(p).exists():
            otworz(Path(p))
        else:
            messagebox.showinfo("Brak", "Nie ma jeszcze transkrypcji ostatniej sesji.")

    def otworz_folder(self):
        k = N.folder_nagran(self.cfg)
        k.mkdir(parents=True, exist_ok=True)
        otworz(k)

    # ------------------------------------------------------------ pętla okna
    def rysuj_poziomy(self):
        poz = {}
        if self.nagr:
            poz = {s.etykieta: s.poziom for s in self.nagr.sciezki}
            for s in self.nagr.sciezki:
                s.poziom *= 0.8
        elif self.bot_katalog is not None:
            poz = dict(self.bot_poziomy)
            if self.zapas:
                for s in self.zapas.sciezki:
                    poz["MG (lokalnie)"] = s.poziom
                    s.poziom *= 0.8
        c = self.c_poz
        c.delete("all")
        w = max(c.winfo_width(), 200)
        h = 16
        c.configure(height=max(60, len(poz) * (h + 4) + 8))
        for i, (n, v) in enumerate(poz.items()):
            y = 4 + i * (h + 4)
            c.create_text(6, y + h / 2, text=n[:22], anchor="w", font=("Segoe UI", 9))
            c.create_rectangle(170, y, w - 8, y + h, outline="#c9b28a")
            c.create_rectangle(170, y, 170 + (w - 178) * min(1.0, v * 3), y + h, fill="#a4502a", width=0)

    def petla(self):
        try:
            while True:
                typ, d = self.q.get_nowait()
                if typ == "log":
                    self.log(d)
                elif typ == "bot":
                    self.zdarzenie_bota(d)
                elif typ == "postep":
                    self.postep(d)
                elif typ == "koniec_nagrania":
                    self.b_nagr.configure(text="● Start", state="normal")
                    self.log("Gotowe. Możesz transkrybować.")
                elif typ == "koniec_transkr":
                    self.b_tr.configure(state="normal")
                    if d != 0:
                        self.log(f"Transkrypcja przerwana (kod {d}).")
        except queue.Empty:
            pass
        if self.nagrywa():
            self.l_czas.configure(text=time.strftime("%H:%M:%S", time.gmtime(time.time() - self.t0)))
        self.rysuj_poziomy()
        self.root.after(200, self.petla)

    def zamknij(self):
        if self.nagrywa() and not messagebox.askyesno("Nagrywanie trwa", "Zatrzymać nagrywanie i zamknąć?"):
            return
        self.zapisz_ustawienia()
        if self.nagr:
            self.nagr.stop(kompresja=False)
        if self.zapas:
            self.zapas.stop(kompresja=False)
        if self.bot and self.bot.poll() is None:
            self.bot_pisz("koniec")
            try:
                self.bot.wait(5)
            except subprocess.TimeoutExpired:
                self.bot.kill()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if WINDOWS else "clam")
    except tk.TclError:
        pass
    Okno(root)
    root.mainloop()


if __name__ == "__main__":
    main()
