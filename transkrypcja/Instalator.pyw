"""Instalator programu Sesja — okno krok po kroku zamiast konsoli.

Uruchamia go instaluj.bat (który najpierw znajduje albo instaluje Pythona 3.12).
Korzysta tylko z biblioteki standardowej, bo działa jeszcze przed instalacją pakietów.
Log całej instalacji trafia do instalacja.log obok tego pliku.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

TU = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
BEZ_OKNA = 0x08000000 if WINDOWS else 0  # CREATE_NO_WINDOW
VENV = TU / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
VENV_PYW = VENV / ("Scripts/pythonw.exe" if WINDOWS else "bin/python")
LOG = TU / "instalacja.log"
WERSJE_OK = ((3, 10), (3, 13))  # onnxruntime i ctranslate2 mają koła dla tych wersji
NODE_URL = "https://nodejs.org/"
PYTHON_URL = "https://www.python.org/downloads/release/python-31210/"

IKONY = {"czeka": "○", "trwa": "◔", "ok": "✔", "blad": "✖", "pomin": "–"}
KOLORY = {"czeka": "#888", "trwa": "#1a6fc9", "ok": "#1d8a3a", "blad": "#c62828", "pomin": "#999"}


def python_konsolowy() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def znajdz_node() -> str | None:
    n = shutil.which("node")
    if n:
        return n
    if WINDOWS:  # świeżo zainstalowany Node nie jest jeszcze w PATH tego procesu
        for baza in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if baza:
                for p in (Path(baza) / "nodejs" / "node.exe", Path(baza) / "Programs" / "nodejs" / "node.exe"):
                    if p.exists():
                        return str(p)
    return None


def wykryj_nvidia() -> str | None:
    smi = shutil.which("nvidia-smi")
    if not smi and WINDOWS:
        p = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        smi = str(p) if p.exists() else None
    if not smi:
        return None
    try:
        out = subprocess.run([smi, "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                             text=True, timeout=15, creationflags=BEZ_OKNA).stdout.strip()
        return out.splitlines()[0] if out else "karta NVIDIA"
    except Exception:
        return None


class Przerwano(Exception):
    pass


class Krok:
    def __init__(self, klucz: str, tytul: str):
        self.klucz, self.tytul = klucz, tytul
        self.stan = "czeka"
        self.ikona: tk.Label | None = None
        self.opis: tk.Label | None = None


class Instalator:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Sesja — instalacja")
        root.minsize(640, 560)
        self.q: queue.Queue = queue.Queue()
        self.watek: threading.Thread | None = None
        self.proc: subprocess.Popen | None = None
        self.przerwij = False
        self.gpu_nazwa = wykryj_nvidia()
        self.node = znajdz_node()
        self.kroki = [
            Krok("python", "Python"),
            Krok("venv", "Własne środowisko programu (.venv)"),
            Krok("pakiety", "Pakiety: faster-whisper, nagrywanie dźwięku"),
            Krok("cuda", "Biblioteki karty NVIDIA (CUDA, ok. 1 GB)"),
            Krok("test", "Sprawdzenie: czy wszystko się ładuje"),
            Krok("bot", "Bot Discord (Node.js, pakiety npm)"),
            Krok("skrot", "Skrót „Sesja” na pulpicie"),
        ]
        self.k = {k.klucz: k for k in self.kroki}
        LOG.write_text(f"Instalacja {time.strftime('%Y-%m-%d %H:%M:%S')}\nPython: {sys.version}\n"
                       f"Folder: {TU}\n", encoding="utf-8")
        self.zbuduj()
        root.protocol("WM_DELETE_WINDOW", self.zamknij)
        root.after(100, self.petla)

    # ------------------------------------------------------------ układ
    def zbuduj(self):
        r = self.root
        f = ttk.Frame(r, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Instalacja programu Sesja", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(f, text="Nagrywanie i transkrypcja sesji. Instalator sam pobierze, co potrzeba "
                          "(kilka minut, z kartą NVIDIA dłużej). Możesz go uruchamiać ponownie — "
                          "dokończy albo naprawi instalację.", wraplength=600, justify="left").pack(anchor="w", pady=(2, 10))

        opc = ttk.LabelFrame(f, text="Co zainstalować", padding=8)
        opc.pack(fill="x")
        self.v_gpu = tk.BooleanVar(value=bool(self.gpu_nazwa))
        gpu_txt = f"Liczenie na karcie NVIDIA — wykryto: {self.gpu_nazwa}" if self.gpu_nazwa else \
            "Liczenie na karcie NVIDIA — nie wykryto karty (sterownik?)"
        ttk.Checkbutton(opc, text=gpu_txt, variable=self.v_gpu).pack(anchor="w")

        wiersz = ttk.Frame(opc)
        wiersz.pack(fill="x", anchor="w")
        self.v_bot = tk.BooleanVar(value=True)
        self.cb_bot = ttk.Checkbutton(wiersz, variable=self.v_bot)
        self.cb_bot.pack(side="left")
        self.b_node = ttk.Button(wiersz, text="Zainstaluj Node.js", command=self.instaluj_node)
        self.odswiez_node()

        self.v_skrot = tk.BooleanVar(value=True)
        ttk.Checkbutton(opc, text="Skrót „Sesja” na pulpicie", variable=self.v_skrot).pack(anchor="w")

        lista = ttk.LabelFrame(f, text="Kroki", padding=8)
        lista.pack(fill="x", pady=10)
        for i, k in enumerate(self.kroki):
            k.ikona = tk.Label(lista, text=IKONY["czeka"], fg=KOLORY["czeka"], font=("Segoe UI", 12), width=2)
            k.ikona.grid(row=i, column=0, sticky="w")
            ttk.Label(lista, text=k.tytul).grid(row=i, column=1, sticky="w")
            k.opis = tk.Label(lista, text="", fg="#666", anchor="w")
            k.opis.grid(row=i, column=2, sticky="w", padx=(12, 0))
        lista.columnconfigure(2, weight=1)

        self.pasek = ttk.Progressbar(f, mode="determinate", maximum=len(self.kroki))
        self.pasek.pack(fill="x")
        self.status = ttk.Label(f, text="Kliknij „Instaluj”.")
        self.status.pack(anchor="w", pady=(4, 6))

        przyc = ttk.Frame(f)
        przyc.pack(fill="x")
        self.b_inst = ttk.Button(przyc, text="Instaluj", command=self.start)
        self.b_inst.pack(side="left")
        self.b_sesja = ttk.Button(przyc, text="Uruchom Sesję", command=self.uruchom_sesje)
        self.b_szcz = ttk.Button(przyc, text="Pokaż szczegóły", command=self.przelacz_log)
        self.b_szcz.pack(side="right")
        self.b_logf = ttk.Button(przyc, text="Otwórz plik logu", command=self.otworz_log)
        self.b_logf.pack(side="right", padx=6)

        self.ramka_log = ttk.Frame(f)
        self.log = scrolledtext.ScrolledText(self.ramka_log, height=14, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log_widoczny = False

    def odswiez_node(self):
        self.b_node.pack_forget()
        if self.node:
            self.cb_bot.config(text=f"Tryb bota Discord (każdy gracz osobno) — Node.js jest")
        else:
            self.cb_bot.config(text="Tryb bota Discord — brak Node.js")
            self.v_bot.set(False)
            self.b_node.pack(side="left", padx=8)

    def przelacz_log(self, pokaz: bool | None = None):
        pokaz = (not self.log_widoczny) if pokaz is None else pokaz
        if pokaz and not self.log_widoczny:
            self.ramka_log.pack(fill="both", expand=True, pady=(8, 0))
        elif not pokaz and self.log_widoczny:
            self.ramka_log.pack_forget()
        self.log_widoczny = pokaz
        self.b_szcz.config(text="Ukryj szczegóły" if pokaz else "Pokaż szczegóły")

    def otworz_log(self):
        if WINDOWS:
            os.startfile(LOG)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(LOG)])

    # ------------------------------------------------------------ komunikacja z wątkiem
    def petla(self):
        try:
            while True:
                co, *a = self.q.get_nowait()
                if co == "log":
                    self.log.config(state="normal")
                    self.log.insert("end", a[0] + "\n")
                    self.log.see("end")
                    self.log.config(state="disabled")
                elif co == "krok":
                    k = self.k[a[0]]
                    k.stan = a[1]
                    k.ikona.config(text=IKONY[a[1]], fg=KOLORY[a[1]])
                    if a[2] is not None:
                        k.opis.config(text=a[2], fg=KOLORY["blad"] if a[1] == "blad" else "#666")
                    self.pasek.config(value=sum(x.stan in ("ok", "pomin") for x in self.kroki))
                elif co == "opis":
                    self.k[a[0]].opis.config(text=a[1])
                elif co == "status":
                    self.status.config(text=a[0])
                elif co == "koniec":
                    self.koniec(*a)
                elif co == "node":
                    self.node = znajdz_node()
                    self.b_node.config(state="normal", text="Zainstaluj Node.js")
                    self.odswiez_node()
                    if self.node:
                        self.v_bot.set(True)
                    else:
                        messagebox.showinfo("Node.js", "Nie udało się zainstalować Node.js automatycznie.\n"
                                            "Otwieram nodejs.org — pobierz wersję LTS, zainstaluj i wróć tutaj.")
                        webbrowser.open(NODE_URL)
        except queue.Empty:
            pass
        self.root.after(100, self.petla)

    def wpis(self, tekst: str):
        with LOG.open("a", encoding="utf-8") as f:
            f.write(tekst + "\n")
        self.q.put(("log", tekst))

    def krok(self, klucz: str, stan: str, opis: str | None = None):
        self.wpis(f"--- [{klucz}] {stan}{': ' + opis if opis else ''}")
        self.q.put(("krok", klucz, stan, opis))

    def uruchom(self, cmd: list[str], klucz: str | None = None, cwd: Path = TU, env: dict | None = None,
                parsuj=None) -> int:
        """Uruchamia polecenie bez okna konsoli, przepisuje wyjście do logu."""
        self.wpis("> " + " ".join(cmd))
        self.proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                     creationflags=BEZ_OKNA)
        for linia in self.proc.stdout:  # type: ignore[union-attr]
            linia = linia.rstrip()
            if not linia:
                continue
            self.wpis(linia)
            if klucz and parsuj:
                opis = parsuj(linia)
                if opis:
                    self.q.put(("opis", klucz, opis))
            if self.przerwij:
                self.proc.kill()
        kod = self.proc.wait()
        self.proc = None
        if self.przerwij:
            raise Przerwano()
        return kod

    # ------------------------------------------------------------ instalacja
    def start(self):
        if self.watek and self.watek.is_alive():
            return
        self.przerwij = False
        self.b_inst.config(state="disabled")
        self.b_sesja.pack_forget()
        for k in self.kroki:
            self.q.put(("krok", k.klucz, "czeka", ""))
        opcje = dict(gpu=self.v_gpu.get(), bot=self.v_bot.get(), skrot=self.v_skrot.get())
        self.watek = threading.Thread(target=self.instaluj, args=(opcje,), daemon=True)
        self.watek.start()

    def instaluj(self, o: dict):
        teraz = None
        try:
            for klucz, fn in [("python", self.k_python), ("venv", self.k_venv), ("pakiety", self.k_pakiety),
                              ("cuda", self.k_cuda), ("test", self.k_test), ("bot", self.k_bot),
                              ("skrot", self.k_skrot)]:
                teraz = klucz
                self.krok(klucz, "trwa", "")
                self.q.put(("status", f"{self.k[klucz].tytul}…"))
                wynik = fn(o)
                if wynik is False:
                    self.krok(klucz, "pomin", "pominięte")
                else:
                    self.krok(klucz, "ok", wynik or "")
            self.q.put(("koniec", True, "Gotowe. Program Sesja jest zainstalowany."))
        except Przerwano:
            self.krok(teraz, "blad", "przerwano")
            self.q.put(("koniec", False, "Przerwano."))
        except Exception as e:
            self.krok(teraz, "blad", str(e).splitlines()[0][:90])
            self.wpis(f"BŁĄD: {e}")
            self.q.put(("koniec", False, f"Błąd: {e}"))

    def k_python(self, o):
        v = sys.version_info[:2]
        if not (WERSJE_OK[0] <= v <= WERSJE_OK[1]):
            raise RuntimeError(f"Python {v[0]}.{v[1]} jest za nowy/za stary — potrzebny 3.10–3.13 "
                               f"(najlepiej 3.12). Uruchom instaluj.bat, on go doinstaluje.")
        return f"{sys.version.split()[0]}, {Path(sys.executable).parent}"

    def k_venv(self, o):
        moja = "%d.%d" % sys.version_info[:2]
        if VENV_PY.exists():
            try:
                jego = subprocess.run([str(VENV_PY), "-c", "import sys;print('%d.%d'%sys.version_info[:2])"],
                                      capture_output=True, text=True, timeout=60, creationflags=BEZ_OKNA).stdout.strip()
            except Exception:
                jego = "?"
            if jego == moja:
                self.wpis(f"Środowisko .venv już jest (Python {jego}).")
                self.uruchom([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"])
                return f"jest (Python {jego})"
            self.wpis(f"Stare .venv ma Pythona {jego or '?'}, a potrzebny {moja} — tworzę od nowa.")
            shutil.rmtree(VENV, ignore_errors=True)
        elif VENV.exists():
            shutil.rmtree(VENV, ignore_errors=True)
        if self.uruchom([python_konsolowy(), "-m", "venv", str(VENV)]) != 0 or not VENV_PY.exists():
            raise RuntimeError("Nie udało się utworzyć .venv (szczegóły w logu).")
        self.uruchom([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"])
        return f"utworzone (Python {moja})"

    @staticmethod
    def parsuj_pip(linia: str) -> str | None:
        m = re.match(r"\s*(Collecting|Downloading|Installing collected packages:)\s*(\S+)?", linia)
        if not m:
            return None
        if m.group(1).startswith("Installing"):
            return "instaluję pobrane pakiety…"
        nazwa = (m.group(2) or "").split("/")[-1]
        nazwa = re.split(r"[<>=!;\[]|-\d", nazwa)[0]
        return ("pobieram " if m.group(1) == "Downloading" else "sprawdzam ") + nazwa

    def pip(self, klucz: str, *pakiety: str):
        kod = self.uruchom([str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check",
                            "--progress-bar", "off", *pakiety], klucz=klucz, parsuj=self.parsuj_pip)
        if kod != 0:
            raise RuntimeError("pip zgłosił błąd (szczegóły w logu).")

    def k_pakiety(self, o):
        self.pip("pakiety", "-r", str(TU / "requirements.txt"))
        return "zainstalowane"

    def k_cuda(self, o):
        if not o["gpu"]:
            return False
        self.pip("cuda", "nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10")
        return "zainstalowane"

    def k_test(self, o):
        kod = ("import sys;sys.path.insert(0,'.');import transkrybuj as T;T.dll_cuda_windows();"
               "import faster_whisper,ctranslate2,soundfile,numpy;import nagrywaj;"
               "print('GPU:',ctranslate2.get_cuda_device_count())")
        out = subprocess.run([str(VENV_PY), "-c", kod], cwd=TU, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=300, creationflags=BEZ_OKNA)
        self.wpis(out.stdout + out.stderr)
        if out.returncode != 0:
            ostatnia = (out.stderr.strip().splitlines() or ["nieznany błąd"])[-1]
            raise RuntimeError(f"Pakiety się nie ładują: {ostatnia}")
        gpu = re.search(r"GPU: (\d+)", out.stdout)
        if o["gpu"] and gpu and gpu.group(1) == "0":
            return "działa, ale karta niewidoczna — transkrypcja na procesorze (zaktualizuj sterownik)"
        return "działa" + (" na karcie NVIDIA" if gpu and gpu.group(1) != "0" else " (procesor)")

    def k_bot(self, o):
        if not o["bot"]:
            return False
        node = znajdz_node()
        if not node:
            raise RuntimeError("Brak Node.js — kliknij „Zainstaluj Node.js” albo odznacz tryb bota.")
        env = dict(os.environ)
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        wersja = subprocess.run([node, "--version"], capture_output=True, text=True,
                                creationflags=BEZ_OKNA).stdout.strip()
        if int(re.sub(r"\D", "", wersja.split(".")[0]) or 0) < 20:
            raise RuntimeError(f"Node.js {wersja} jest za stary — potrzebny 20 lub nowszy (LTS z nodejs.org).")
        npm = ["cmd", "/c", "npm"] if WINDOWS else ["npm"]
        kod = self.uruchom([*npm, "install", "--omit=dev", "--no-audit", "--no-fund"], klucz="bot",
                           cwd=TU / "bot", env=env, parsuj=lambda l: "npm: " + l[:60] if "added" in l else None)
        if kod != 0:
            raise RuntimeError("npm install zgłosił błąd (szczegóły w logu).")
        return f"Node {wersja}, pakiety zainstalowane"

    def k_skrot(self, o):
        if not o["skrot"] or not WINDOWS:
            return False
        e = lambda s: str(s).replace("'", "''")
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\\Sesja.lnk');"
              f"$s.TargetPath='{e(VENV_PYW)}';$s.Arguments='\"{e(TU / 'Sesja.pyw')}\"';"
              f"$s.WorkingDirectory='{e(TU)}';$s.Description='Nagrywanie i transkrypcja sesji';$s.Save()")
        if self.uruchom(["powershell", "-NoProfile", "-Command", ps]) != 0:
            raise RuntimeError("Nie udało się zrobić skrótu (szczegóły w logu). Program działa przez start.bat.")
        return "na pulpicie"

    # ------------------------------------------------------------ Node.js
    def instaluj_node(self):
        if not WINDOWS or not shutil.which("winget"):
            webbrowser.open(NODE_URL)
            return
        if not messagebox.askyesno("Node.js", "Zainstalować Node.js LTS przez winget?\n"
                                   "Windows może poprosić o zgodę administratora."):
            return
        self.b_node.config(state="disabled", text="Instaluję Node.js…")
        self.przelacz_log(True)

        def praca():
            try:
                self.uruchom(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                              "--accept-package-agreements", "--accept-source-agreements"])
            except Exception as ex:
                self.wpis(f"winget: {ex}")
            self.q.put(("node",))
        threading.Thread(target=praca, daemon=True).start()

    # ------------------------------------------------------------ koniec
    def koniec(self, ok: bool, tekst: str):
        self.status.config(text=tekst)
        self.b_inst.config(state="normal", text="Instaluj" if ok else "Spróbuj ponownie")
        if ok:
            self.b_sesja.pack(side="left", padx=8)
        else:
            self.przelacz_log(True)
            messagebox.showerror("Instalacja", f"{tekst}\n\nPełny log: {LOG}\n"
                                 "Możesz go wysłać na czat (nie zawiera tokenu bota).")

    def uruchom_sesje(self):
        subprocess.Popen([str(VENV_PYW), str(TU / "Sesja.pyw")], cwd=TU, creationflags=BEZ_OKNA)
        self.root.destroy()

    def zamknij(self):
        if self.watek and self.watek.is_alive():
            if not messagebox.askyesno("Instalacja", "Instalacja trwa. Przerwać?"):
                return
            self.przerwij = True
            if self.proc:
                self.proc.kill()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if WINDOWS else "clam")
    except tk.TclError:
        pass
    Instalator(root)
    root.mainloop()


if __name__ == "__main__":
    main()
