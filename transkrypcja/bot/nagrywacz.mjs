// Bot nagrywający: każdy gracz na kanale głosowym do osobnego pliku WAV (jak Craig).
//
// Sterowanie:
//   • na Discordzie: /nagrywaj (bot wchodzi na Twój kanał), /stop
//   • z okna Sesja.pyw przez stdin: linie „start”, „stop”, „koniec”
// Na stdout wypisuje linie JSON dla okna: {"log":…}, {"zdarzenie":…}, {"poziomy":{…}}.
//
// Token: plik bot/token.txt (poza gitem) albo zmienna środowiskowa DISCORD_TOKEN.
//
// Zgody: nagrywa tylko tych, którzy się zgodzili (patrz Zgody niżej). Kogo nie wolno nagrywać,
// tego strumienia bot w ogóle nie subskrybuje — jego dźwięk nie trafia do żadnego pliku.
// Odbiór dźwięku z szyfrowaniem end-to-end Discorda (DAVE) robi @discordjs/voice ≥ 0.19.2 (+ @snazzah/davey).

import { Client, GatewayIntentBits, Events, ApplicationCommandType } from "discord.js";
import {
  joinVoiceChannel, entersState, VoiceConnectionStatus, EndBehaviorType,
} from "@discordjs/voice";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const TU = path.dirname(fileURLToPath(import.meta.url));
const GLOWNY = path.resolve(TU, "..");
const RATE = 48000;
const PAD_PROG = 0.25;   // s
const FIX_CO = 5000;     // ms: co ile poprawiać nagłówek WAV + fsync
const require = createRequire(import.meta.url);

// ------------------------------------------------------------------ wyjście dla okna
const wyslij = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const log = (t) => wyslij({ log: t });

// ------------------------------------------------------------------ ustawienia, token
function ustawienia() {
  try { return JSON.parse(fs.readFileSync(path.join(GLOWNY, "ustawienia.json"), "utf8")); } catch { return {}; }
}
function token() {
  if (process.env.DISCORD_TOKEN) return process.env.DISCORD_TOKEN.trim();
  try { return fs.readFileSync(path.join(TU, "token.txt"), "utf8").trim(); } catch { return ""; }
}
function kluczZgod() {
  try { return fs.readFileSync(path.join(TU, "zgody_klucz.txt"), "utf8").trim(); } catch { return ""; }
}
function arg(nazwa) {
  const i = process.argv.indexOf(nazwa);
  return i > 0 ? process.argv[i + 1] : undefined;
}

// ------------------------------------------------------------------ zgody
// Nick → porównywalny klucz: NFKC zamienia ozdobne litery Unicode (𝐳𝐲𝐜𝐡𝐮) na zwykłe (zychu).
export const norm = (s) => String(s ?? "").normalize("NFKC").trim().toLowerCase();
const lista = (x) => (Array.isArray(x) ? x : String(x ?? "").split(/[,;\n]/)).map(norm).filter(Boolean);
const URL_ZGOD = "https://rozdroza.vulpescancrosa.workers.dev/api/watcher/zgody";

/** Lista zgód na jedną sesję. zrodlo: "hub" (lista pobrana), "blad" (klucz jest, lista nie — nagrywa tylko MG),
 *  "lokalnie" (brak klucza — nagrywa wszystkich poza listą „Nie nagrywaj”). */
export class Zgody {
  constructor(cfg, hub = null, zrodlo = "lokalnie", powod = "") {
    const z = cfg.zgody || {};
    this.zablokowani = new Set(lista(z.zablokowani));
    this.dopuszczeni = new Set(lista(z.dopuszczeni));
    this.mg = norm(cfg.bot?.mg);
    this.zrodlo = zrodlo; this.powod = powod;
    this.nagrywaj = new Set((hub?.nagrywaj || []).map(String));
  }
  static async pobierz(cfg, fetchFn = globalThis.fetch) {
    const klucz = kluczZgod();
    if (!klucz) return new Zgody(cfg, null, "lokalnie", "brak klucza zgód");
    const z = cfg.zgody || {};
    const url = `${z.url || URL_ZGOD}?kampania=${encodeURIComponent(z.kampania || "fallout-equestria")}`;
    try {
      const r = await fetchFn(url, { headers: { Authorization: `Bearer ${klucz}` }, signal: AbortSignal.timeout(8000) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        const opis = { 401: "zły klucz zgód", 503: "HUB nie ma skonfigurowanych zgód", 404: "nieznana kampania" }[r.status];
        return new Zgody(cfg, null, "blad", `${opis || "HUB odpowiedział " + r.status}${j.error ? ` (${j.error})` : ""}`);
      }
      return new Zgody(cfg, j, "hub", `osoby ze zgodą: ${(j.nagrywaj || []).length}`);
    } catch (e) {
      return new Zgody(cfg, null, "blad", `brak połączenia z HUB-em (${e.name === "TimeoutError" ? "przekroczony czas" : e.message})`);
    }
  }
  /** → [czy nagrywać, powód]. Kolejność: „Nie nagrywaj” > MG > „Dopuść” > lista HUB-a. */
  decyzja(kto) {
    const klucze = [kto.id, kto.uzytkownik, kto.etykieta].map(norm).filter(Boolean);
    const jest = (zb) => klucze.some((k) => zb.has(k));
    if (jest(this.zablokowani)) return [false, "na liście „Nie nagrywaj”"];
    if (this.mg && klucze.includes(this.mg)) return [true, "MG"];
    if (jest(this.dopuszczeni)) return [true, "dopuszczony ręcznie"];
    if (this.zrodlo === "hub") return this.nagrywaj.has(String(kto.id)) ? [true, "zgoda w HUB-ie"] : [false, "brak zgody w HUB-ie"];
    if (this.zrodlo === "blad") return [false, `lista zgód niedostępna (${this.powod}) — nagrywam tylko MG`];
    return [true, "bez listy zgód"];
  }
  opis() {
    if (this.zrodlo === "hub") return `Zgody z HUB-a: ${this.powod}. Pozostałych nie nagrywam.`;
    if (this.zrodlo === "blad") return `⚠ Lista zgód niedostępna: ${this.powod}. Nagrywam tylko MG i dopuszczonych ręcznie.`;
    return `Zgody: bez HUB-a (${this.powod}) — nagrywam wszystkich poza listą „Nie nagrywaj” (${this.zablokowani.size}).`;
  }
}

// ------------------------------------------------------------------ dekoder Opus
function dekoder() {
  try {
    const { OpusEncoder } = require("@discordjs/opus");   // szybszy, natywny (opcjonalny)
    const e = new OpusEncoder(RATE, 2);
    return (pkt) => e.decode(pkt);
  } catch {
    const OpusScript = require("opusscript");            // czysty JS/WASM, zawsze działa
    const e = new OpusScript(RATE, 2, OpusScript.Application.AUDIO);
    return (pkt) => Buffer.from(e.decode(pkt));
  }
}

// ------------------------------------------------------------------ WAV na bieżąco (jak w nagrywaj.py)
export class WavNaBiezaco {
  constructor(plik, rate = RATE) {
    this.plik = plik; this.rate = rate; this.probki = 0; this.ostatniFix = 0;
    this.fd = fs.openSync(plik, "w");
    this.pozycja = 44;
    this.naglowek();
  }
  naglowek() {
    const dane = this.probki * 2, h = Buffer.alloc(44);
    h.write("RIFF", 0); h.writeUInt32LE(36 + dane, 4); h.write("WAVE", 8);
    h.write("fmt ", 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22);
    h.writeUInt32LE(this.rate, 24); h.writeUInt32LE(this.rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34);
    h.write("data", 36); h.writeUInt32LE(dane, 40);
    fs.writeSync(this.fd, h, 0, 44, 0);
  }
  pisz(buf) {   // buf: Int16 mono LE
    fs.writeSync(this.fd, buf, 0, buf.length, this.pozycja);
    this.pozycja += buf.length; this.probki += buf.length / 2;
    const teraz = Date.now();
    if (teraz - this.ostatniFix > FIX_CO) { this.naglowek(); fs.fsyncSync(this.fd); this.ostatniFix = teraz; }
  }
  zamknij() { this.naglowek(); fs.fsyncSync(this.fd); fs.closeSync(this.fd); }
}

/** Jedna osoba: PCM stereo 48 kHz → mono, wyrównane do wspólnego zegara (cisza, gdy milczy). */
export class Sciezka {
  constructor(plik, t0, teraz = () => Date.now() / 1000) {
    this.wav = new WavNaBiezaco(plik); this.t0 = t0; this.teraz = teraz; this.poziom = 0;
  }
  dopelnij(odejmij = 0) {
    const oczekiwane = Math.floor((this.teraz() - this.t0) * RATE) - odejmij;
    const brak = oczekiwane - this.wav.probki;
    if (brak > PAD_PROG * RATE) this.wav.pisz(Buffer.alloc(brak * 2));
  }
  blokStereo(pcm) {
    const n = pcm.length / 4, mono = Buffer.alloc(n * 2);
    let max = 0;
    for (let i = 0; i < n; i++) {
      const v = (pcm.readInt16LE(i * 4) + pcm.readInt16LE(i * 4 + 2)) >> 1;
      mono.writeInt16LE(v, i * 2);
      const a = v < 0 ? -v : v; if (a > max) max = a;
    }
    this.dopelnij(n);
    this.wav.pisz(mono);
    this.poziom = Math.max(this.poziom * 0.7, max / 32768);
  }
  zamknij() { this.dopelnij(); this.wav.zamknij(); }
}

// ------------------------------------------------------------------ sesja nagrania
function znacznik(d = new Date()) {
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}
function isoLokalny(d = new Date()) {
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

class Sesja {
  constructor(kanal, folder, zgody) {
    this.kanal = kanal; this.guild = kanal.guild; this.zgody = zgody;
    this.pominieci = new Map();   // userId → {etykieta, powod}
    this.t0 = Date.now() / 1000;
    this.katalog = path.join(folder, `${znacznik()}_bot`);
    fs.mkdirSync(this.katalog, { recursive: true });
    this.sciezki = new Map();     // userId → {sciezka, meta}
    this.meta = { start: isoLokalny(), tryb: "bot", serwer: this.guild.name, kanal: kanal.name, sciezki: [],
                  zgody: zgody.zrodlo };
    this.zapiszMeta();
  }
  zapiszMeta() {
    fs.writeFileSync(path.join(this.katalog, "sesja.json"), JSON.stringify(this.meta, null, 2), "utf8");
  }
  async start() {
    this.conn = joinVoiceChannel({
      channelId: this.kanal.id, guildId: this.guild.id,
      adapterCreator: this.guild.voiceAdapterCreator, selfDeaf: false, selfMute: true,
    });
    let bledyDave = 0;
    this.conn.on("debug", (m) => {
      if (/decrypt/i.test(m) && bledyDave++ < 20) log(`[voice] ${m}`);
    });
    this.conn.on(VoiceConnectionStatus.Disconnected, async () => {
      try {
        await Promise.race([
          entersState(this.conn, VoiceConnectionStatus.Signalling, 5000),
          entersState(this.conn, VoiceConnectionStatus.Connecting, 5000),
        ]);
        log("Połączenie głosowe wznowione.");
      } catch {
        log("Bot został rozłączony z kanału — zamykam nagranie.");
        this.stop();
      }
    });
    await entersState(this.conn, VoiceConnectionStatus.Ready, 30000);
    this.dekoduj = dekoder;
    this.conn.receiver.speaking.on("start", (uid) => this.subskrybuj(uid).catch((e) => log(`Błąd ścieżki ${uid}: ${e.message}`)));
    this.timer = setInterval(() => this.poziomy(), 500);
    wyslij({ zdarzenie: "start", katalog: this.katalog, kanal: this.kanal.name, serwer: this.guild.name });
    log(`Nagrywam kanał „${this.kanal.name}” (${this.guild.name}) do ${this.katalog}`);
  }
  async subskrybuj(uid) {
    if (this.sciezki.has(uid) || this.pominieci.has(uid) || this.zatrzymana) return;
    this.sciezki.set(uid, null);  // rezerwacja, zanim przyjdzie członek z API
    const m = await this.guild.members.fetch(uid).catch(() => null);
    if (m?.user?.bot) return;
    const meta = {
      etykieta: m?.displayName ?? uid, uzytkownik: m?.user?.username ?? uid, id: uid, plik: uid, rate: RATE,
    };
    const [wolno, powod] = this.zgody.decyzja(meta);
    if (!wolno || this.zatrzymana) {
      this.sciezki.delete(uid);
      this.pominieci.set(uid, { etykieta: meta.etykieta, powod });
      wyslij({ zdarzenie: "pominiety", kto: meta.etykieta, uzytkownik: meta.uzytkownik, id: uid, powod });
      log(`○ nie nagrywam: ${meta.etykieta} (${meta.uzytkownik}, ID ${uid}) — ${powod}`);
      return;
    }
    const sc = new Sciezka(path.join(this.katalog, `${uid}.wav`), this.t0);
    this.sciezki.set(uid, { sciezka: sc, meta });
    this.meta.sciezki.push(meta); this.zapiszMeta();
    const dekoduj = this.dekoduj();
    const strumien = this.conn.receiver.subscribe(uid, { end: { behavior: EndBehaviorType.Manual } });
    let bledy = 0;
    strumien.on("data", (pakiet) => {
      try { sc.blokStereo(dekoduj(pakiet)); } catch (e) { if (bledy++ < 5) log(`Uszkodzony pakiet od ${meta.etykieta}: ${e.message}`); }
    });
    strumien.on("error", (e) => log(`Strumień ${meta.etykieta}: ${e.message}`));
    this.sciezki.get(uid).strumien = strumien;
    log(`● nowa ścieżka: ${meta.etykieta} (${meta.uzytkownik}, ID ${uid}) — ${powod}`);
  }
  /** Nowa lista zgód w trakcie sesji: kto stracił zgodę — przestaje być nagrywany; pominięci są oceniani od nowa. */
  zmienZgody(zgody) {
    this.zgody = zgody;
    log(zgody.opis());
    for (const [uid, v] of this.sciezki) {
      if (!v || v.wylaczona) continue;
      const [wolno, powod] = zgody.decyzja(v.meta);
      if (!wolno) {
        v.wylaczona = true;
        try { v.strumien?.destroy(); } catch {}
        this.conn?.receiver?.subscriptions?.delete?.(uid);
        v.meta.przerwana = isoLokalny(); this.zapiszMeta();
        wyslij({ zdarzenie: "pominiety", kto: v.meta.etykieta, uzytkownik: v.meta.uzytkownik, id: uid, powod });
        log(`○ przestaję nagrywać: ${v.meta.etykieta} — ${powod} (to, co już nagrane, zostaje w ${uid}.wav)`);
      }
    }
    this.pominieci.clear();   // przy następnym odezwaniu się zdecyduje nowa lista
    wyslij({ zdarzenie: "pominieci_wyczysc" });
  }
  poziomy() {
    const p = {};
    for (const v of this.sciezki.values()) if (v && !v.wylaczona) { p[v.meta.etykieta] = Math.round(v.sciezka.poziom * 100) / 100; v.sciezka.poziom *= 0.8; }
    wyslij({ poziomy: p, czas: Math.round(Date.now() / 1000 - this.t0) });
  }
  stop() {
    if (this.zatrzymana) return;
    this.zatrzymana = true;
    clearInterval(this.timer);
    for (const v of this.sciezki.values()) if (v) v.sciezka.zamknij();
    this.meta.koniec = isoLokalny(); this.zapiszMeta();
    try { this.conn?.destroy(); } catch {}
    wyslij({ zdarzenie: "stop", katalog: this.katalog });
    log(`Nagranie zakończone: ${this.katalog}`);
  }
}

// ------------------------------------------------------------------ bot
async function main() {
  const tok = token();
  if (!tok) { wyslij({ zdarzenie: "blad", log: "Brak tokenu bota: wklej go w oknie (Bot → Token) albo do bot/token.txt." }); process.exit(2); }
  let cfg = ustawienia();
  const folder = arg("--folder") || cfg.folder_nagran || path.join(GLOWNY, "nagrania");
  let sesja = null;

  const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates] });
  const komendy = [
    { name: "nagrywaj", description: "Bot wchodzi na Twój kanał głosowy i nagrywa każdego osobno", type: ApplicationCommandType.ChatInput },
    { name: "stop", description: "Kończy nagrywanie", type: ApplicationCommandType.ChatInput },
  ];
  const zarejestruj = (g) => g.commands.set(komendy).catch((e) => log(`Nie zarejestrowałem komend na „${g.name}”: ${e.message}`));

  async function zacznij(kanal) {
    if (sesja && !sesja.zatrzymana) return `Już nagrywam kanał „${sesja.kanal.name}”.`;
    cfg = ustawienia();   // świeże ustawienia z okna (MG, „Nie nagrywaj”, „Dopuść”)
    const zgody = await Zgody.pobierz(cfg);
    log(zgody.opis());
    sesja = new Sesja(kanal, folder, zgody);
    try { await sesja.start(); } catch (e) { sesja.stop(); sesja = null; return `Nie udało się wejść na kanał: ${e.message}`; }
    const tylkoZgody = zgody.zrodlo !== "lokalnie" || zgody.zablokowani.size > 0;
    return `🔴 Nagrywam kanał „${kanal.name}”. Każdy głos osobno, do transkrypcji po sesji.` +
      (tylkoZgody ? " Nagrywam tylko osoby, które się zgodziły." : "") + " /stop kończy.";
  }
  function zakoncz() {
    if (!sesja || sesja.zatrzymana) return "Nic nie nagrywam.";
    sesja.stop(); return "⏹️ Nagrywanie zakończone.";
  }
  function kanalMG() {
    const mg = (cfg.bot?.mg || "").toLowerCase();
    const zajete = [];
    for (const g of client.guilds.cache.values()) {
      for (const vs of g.voiceStates.cache.values()) {
        if (!vs.channel || vs.member?.user?.bot) continue;
        const kto = [vs.id, vs.member?.user?.username, vs.member?.displayName].filter(Boolean).map((x) => x.toLowerCase());
        if (mg && kto.includes(mg)) return vs.channel;
        if (!zajete.includes(vs.channel)) zajete.push(vs.channel);
      }
    }
    if (!mg && zajete.length === 1) return zajete[0];
    return null;
  }

  client.once(Events.ClientReady, async (c) => {
    for (const g of c.guilds.cache.values()) await zarejestruj(g);
    wyslij({ zdarzenie: "gotowy", bot: c.user.tag, serwery: c.guilds.cache.map((g) => g.name) });
    log(`Bot ${c.user.tag} gotowy. Serwery: ${c.guilds.cache.map((g) => g.name).join(", ") || "(żaden — zaproś bota)"}`);
  });
  client.on(Events.GuildCreate, zarejestruj);
  // ktoś wchodzi na nagrywany kanał → świeża lista zgód (najwyżej raz na minutę)
  let ostatnieOdswiezenie = 0;
  async function odswiezZgody(wymus = false) {
    if (!sesja || sesja.zatrzymana) return;
    if (!wymus && Date.now() - ostatnieOdswiezenie < 60000) return;
    ostatnieOdswiezenie = Date.now();
    cfg = ustawienia();
    sesja?.zmienZgody(await Zgody.pobierz(cfg));
  }
  client.on(Events.VoiceStateUpdate, (stary, nowy) => {
    if (sesja && !sesja.zatrzymana && nowy.channelId === sesja.kanal.id && stary.channelId !== nowy.channelId
        && !nowy.member?.user?.bot) {
      log(`→ na kanał wchodzi: ${nowy.member?.displayName ?? nowy.id}`);
      odswiezZgody().catch((e) => log(`Zgody: ${e.message}`));
    }
  });
  client.on(Events.InteractionCreate, async (i) => {
    if (!i.isChatInputCommand()) return;
    if (i.commandName === "nagrywaj") {
      const kanal = i.member?.voice?.channel;
      if (!kanal) return i.reply({ content: "Najpierw wejdź na kanał głosowy.", ephemeral: true });
      await i.deferReply();
      await i.editReply(await zacznij(kanal));
    } else if (i.commandName === "stop") {
      await i.reply(zakoncz());
    }
  });

  readline.createInterface({ input: process.stdin }).on("line", async (l) => {
    const k = l.trim().toLowerCase();
    if (k === "start") {
      const kanal = kanalMG();
      if (kanal) {
        const odp = await zacznij(kanal);
        log(odp);
        if (odp.startsWith("🔴")) kanal.send(odp).catch(() => {});   // informacja dla graczy na czacie kanału
      } else log(
        "Nie wiem, który kanał nagrać: wejdź na kanał głosowy (i ustaw swój nick w polu „MG na Discordzie”) albo użyj /nagrywaj.");
    } else if (k === "stop") {
      log(zakoncz());
    } else if (k === "zgody") {   // okno zmieniło „Nie nagrywaj” / „Dopuść” albo klucz
      if (sesja && !sesja.zatrzymana) await odswiezZgody(true);
    } else if (k === "koniec") {
      zakoncz(); await client.destroy(); process.exit(0);
    }
  });
  const sprzatnij = async () => { zakoncz(); await client.destroy(); process.exit(0); };
  process.on("SIGINT", sprzatnij);
  process.on("SIGTERM", sprzatnij);

  await client.login(tok);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => { wyslij({ zdarzenie: "blad", log: `Bot: ${e.message}` }); process.exit(1); });
}
