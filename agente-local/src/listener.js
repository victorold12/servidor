/**
 * Loop de escuta contínua do Agente Local — a peça que faltava pra "Ei, JARVIS"
 * funcionar sem ninguém clicar em nada.
 *
 * COMO FUNCIONA
 *   1. um gravador externo captura o microfone em trechos curtos de WAV
 *      (16 kHz mono, que é o formato que o whisper.cpp quer);
 *   2. cada trecho passa pelo whisper (stt.transcribe);
 *   3. o texto passa por detectWakeWord;
 *   4. deu match → dispara o callback com o comando que veio depois do nome.
 *
 * O QUE ISTO NÃO É
 *   Não é um detector de wake word barato. Um openWakeWord roda um modelinho
 *   de ~1 MB e só chama o ASR quando acha o gatilho; aqui TODO trecho vai pro
 *   whisper, então o loop consome CPU continuamente. Está escrito assim porque
 *   não adiciona dependência nativa nem download de modelo extra — e a conta
 *   fica declarada em vez de escondida (`custo()` devolve a estimativa).
 *
 * GRAVADOR
 *   Node não captura microfone sozinho. Em vez de embutir um módulo nativo
 *   (que quebra a cada versão do Electron), o loop chama um gravador que já
 *   existe na máquina, sempre com `spawn` em array e `shell:false` — mesma
 *   regra do executor de comandos (Seção 8): nada de string passando por shell.
 *
 *   Windows  → ffmpeg (-f dshow), que vem com o próprio JARVIS na maioria dos PCs
 *   Linux    → arecord (alsa-utils) ou ffmpeg (-f alsa)
 *   macOS    → ffmpeg (-f avfoundation) ou sox/rec
 *
 *   Nenhum presente = escuta indisponível, dito com o motivo. Nunca finge
 *   estar ouvindo.
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { detectWakeWord, loadSttConfig, transcribe } from "./stt.js";
import { leJsonConfig } from "./json-config.js";

function baseDir() {
  return process.env.JARVIS_AGENT_DIR || path.join(os.homedir(), ".jarvis-agente");
}
function configFile() { return path.join(baseDir(), "listener.json"); }
function tmpDir() { return path.join(baseDir(), "escuta"); }

/** Trecho de 4s: curto o bastante pra resposta parecer imediata, longo o
 *  bastante pra caber "ei jarvis, abre o chrome" inteiro num só arquivo. */
export const LIMITES = {
  chunkSec: { min: 2, max: 15, default: 4 },
  pausaMs: { min: 0, max: 5000, default: 250 },
};

export function defaults() {
  return {
    enabled: false,           // escuta contínua é opt-in: microfone sempre ligado é decisão do usuário
    recorder: "auto",         // auto | ffmpeg | arecord | sox
    device: "",               // vazio = padrão do sistema
    /* Caminho absoluto do ffmpeg, quando ele NÃO está no PATH.
       Existe porque o instalador dependia do `winget` pra trazer o ffmpeg — e
       winget não é universal: na máquina do Victor ele simplesmente não existe
       (vem no "Instalador de Aplicativo" da Microsoft Store). Sem isto, a única
       saída era mexer no PATH do usuário, que é invasivo e só vale pra
       processos abertos DEPOIS. Mesmo padrão do whisper, que já guarda o
       `binary` em stt.json. Vazio = procura "ffmpeg" no PATH, como antes. */
    ffmpegPath: "",
    chunkSec: LIMITES.chunkSec.default,
    pausaMs: LIMITES.pausaMs.default,
  };
}

export function loadConfig() {
  return { ...defaults(), ...(leJsonConfig(configFile()) || {}) };
}

function clamp(valor, faixa) {
  const n = Number(valor);
  if (valor === null || valor === "" || typeof valor === "boolean" || !Number.isFinite(n)) return null;
  return Math.min(faixa.max, Math.max(faixa.min, n));
}

export function saveConfig(entrada = {}) {
  const out = { ...loadConfig() };
  if (typeof entrada.enabled === "boolean") out.enabled = entrada.enabled;
  if (RECORDERS[entrada.recorder] || entrada.recorder === "auto") out.recorder = entrada.recorder;
  if (typeof entrada.device === "string") out.device = entrada.device.slice(0, 200);
  const c = clamp(entrada.chunkSec, LIMITES.chunkSec);
  if (c !== null) out.chunkSec = c;
  const p = clamp(entrada.pausaMs, LIMITES.pausaMs);
  if (p !== null) out.pausaMs = p;

  fs.mkdirSync(baseDir(), { recursive: true });
  fs.writeFileSync(configFile(), JSON.stringify(out, null, 2), { mode: 0o600 });
  return out;
}

// ------------------------------------------------------------ gravadores
/* Cada entrada monta os argumentos pra gravar UM trecho e sair. Nada de string
   com pipe: array de argumentos, `shell:false`, igual ao executor de comandos. */
export const RECORDERS = {
  ffmpeg: {
    bin: "ffmpeg",
    check: ["-hide_banner", "-version"],
    args(destino, { chunkSec, device }) {
      const entrada = os.platform() === "win32"
        ? ["-f", "dshow", "-i", `audio=${device || "default"}`]
        : os.platform() === "darwin"
          ? ["-f", "avfoundation", "-i", `:${device || "0"}`]
          : ["-f", "alsa", "-i", device || "default"];
      return [
        "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        ...entrada,
        "-t", String(chunkSec),
        "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
        destino,
      ];
    },
  },
  arecord: {
    bin: "arecord",
    check: ["--version"],
    args(destino, { chunkSec, device }) {
      const dev = device ? ["-D", device] : [];
      return [...dev, "-q", "-f", "S16_LE", "-c", "1", "-r", "16000",
              "-d", String(chunkSec), destino];
    },
  },
  sox: {
    bin: "rec",
    check: ["--version"],
    args(destino, { chunkSec }) {
      return ["-q", "-c", "1", "-r", "16000", "-b", "16", destino,
              "trim", "0", String(chunkSec)];
    },
  },
};

/** O executável de um gravador, respeitando o caminho configurado.
 *  Só o ffmpeg tem essa saída — é o único que o instalador baixa. */
function binDe(nome, cfg) {
  if (nome === "ffmpeg" && cfg?.ffmpegPath) return cfg.ffmpegPath;
  return RECORDERS[nome].bin;
}

/** Qual gravador existe nesta máquina? Ordem por plataforma. */
export function detectRecorder(preferido = "auto", cfg = loadConfig()) {
  const ordem = preferido !== "auto" && RECORDERS[preferido]
    ? [preferido]
    : os.platform() === "win32" ? ["ffmpeg"]
      : os.platform() === "darwin" ? ["ffmpeg", "sox"]
        : ["arecord", "ffmpeg", "sox"];

  const tentados = [];
  for (const nome of ordem) {
    const r = RECORDERS[nome];
    const bin = binDe(nome, cfg);
    const teste = spawnSync(bin, r.check, { shell: false, timeout: 4000 });
    // erro pode ser ENOENT (não instalado) — e alguns binários saem !=0 no --version
    if (!teste.error) return { ok: true, recorder: nome, bin };
    tentados.push(`${bin} (${teste.error.code || "falhou"})`);
  }
  return {
    ok: false,
    tried: tentados,
    reason: "nenhum gravador de áudio encontrado",
    /* A dica antiga mandava usar o winget — que não existe em toda máquina, e
       não existia justamente na do Victor. Rodar o instalador de novo resolve
       sem depender dele: ele baixa o ffmpeg direto e grava o caminho aqui. */
    hint: os.platform() === "win32"
      ? "rode o instalador de vozes de novo (ele baixa o ffmpeg), ou deixe ffmpeg.exe no PATH"
      : "instale o alsa-utils (arecord) ou o ffmpeg",
  };
}

/** O que falta pra escuta contínua funcionar. É isto que a aba de config mostra. */
export function checkSetup(cfg = loadConfig()) {
  const gravador = detectRecorder(cfg.recorder, cfg);
  const stt = loadSttConfig();
  const modelo = path.join(stt.modelsDir, `ggml-${stt.model}.bin`);
  const temModelo = fs.existsSync(modelo);
  const faltando = [];
  if (!gravador.ok) faltando.push("gravador de áudio");
  if (!temModelo) faltando.push("modelo do whisper");
  return {
    enabled: cfg.enabled,
    recorder: gravador.ok ? gravador.recorder : null,
    recorder_hint: gravador.ok ? null : gravador.hint,
    recorder_tried: gravador.ok ? undefined : gravador.tried,
    whisper_model: stt.model,
    whisper_model_present: temModelo,
    chunk_sec: cfg.chunkSec,
    ready: gravador.ok && temModelo,
    missing: faltando,
    custo: custo(cfg),
  };
}

/** Estimativa honesta do que a escuta contínua consome. */
export function custo(cfg = loadConfig()) {
  const stt = loadSttConfig();
  const porHora = Math.round(3600 / Math.max(1, cfg.chunkSec));
  return {
    transcricoes_por_hora: porHora,
    modelo: stt.model,
    aviso: `cada trecho de ${cfg.chunkSec}s passa pelo whisper (${stt.model}): ` +
      `~${porHora} transcrições por hora de CPU. Não é um detector de wake word ` +
      "dedicado — é ASR contínuo, e gasta como tal.",
  };
}

// ------------------------------------------------------------ o loop
function gravaTrecho(recorder, destino, cfg) {
  const r = RECORDERS[recorder];
  return new Promise((resolve) => {
    let proc;
    try {
      proc = spawn(binDe(recorder, cfg), r.args(destino, cfg), { shell: false, stdio: ["ignore", "ignore", "pipe"] });
    } catch (e) {
      resolve({ ok: false, reason: String(e.message) });
      return;
    }
    let stderr = "";
    proc.stderr.on("data", (d) => { stderr += String(d).slice(0, 500); });
    // margem: o gravador precisa terminar sozinho; se travar, mata
    const limite = setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} },
                              (cfg.chunkSec + 6) * 1000);
    proc.on("error", (e) => { clearTimeout(limite); resolve({ ok: false, reason: String(e.message) }); });
    proc.on("close", (code) => {
      clearTimeout(limite);
      if (!fs.existsSync(destino)) {
        resolve({ ok: false, reason: `gravador saiu ${code} sem gerar arquivo`, detail: stderr.slice(-200) });
        return;
      }
      resolve({ ok: true, path: destino });
    });
  });
}

/**
 * Cria o loop. Não começa sozinho: quem chama decide quando ligar, e a config
 * `enabled` é opt-in — microfone ligado o tempo todo é decisão do usuário, não
 * padrão do programa.
 *
 * onWake({ command, transcript, greeted }) é chamado a cada match.
 * onError(motivo) recebe falha de gravação/transcrição sem derrubar o loop.
 */
export function createListener({ onWake, onError, onChunk } = {}) {
  let rodando = false;
  let ciclo = null;
  let atual = null;
  const estado = { chunks: 0, hits: 0, erros: 0, ultimoTexto: null, desde: null };

  async function umCiclo(cfg, recorder) {
    const destino = path.join(tmpDir(), `trecho-${Date.now()}.wav`);
    const g = await gravaTrecho(recorder, destino, cfg);
    if (!rodando) { limpa(destino); return; }
    if (!g.ok) {
      estado.erros += 1;
      onError?.(g.reason, g.detail);
      limpa(destino);
      return;
    }
    estado.chunks += 1;
    const t = await transcribe(destino, {}, 60_000);
    /* O áudio do microfone é apagado logo depois de transcrever, sempre — nos
       dois caminhos. Guardar gravação da casa da pessoa em disco não é função
       deste loop. */
    limpa(destino);
    if (!rodando) return;
    if (!t.ok) { estado.erros += 1; onError?.(t.reason, t.hint); return; }

    const texto = t.text || "";
    estado.ultimoTexto = texto || null;
    onChunk?.(texto);
    if (!texto) return;

    const w = detectWakeWord(texto);
    if (w.hit) {
      estado.hits += 1;
      onWake?.({ command: w.command, transcript: texto, greeted: !!w.greeted, matched: w.matched });
    }
  }

  function limpa(p) { try { fs.unlinkSync(p); } catch {} }

  async function laco() {
    while (rodando) {
      const cfg = loadConfig();
      const det = detectRecorder(cfg.recorder);
      if (!det.ok) {
        rodando = false;
        onError?.(det.reason, det.hint);
        return;
      }
      atual = umCiclo(cfg, det.recorder);
      await atual;
      atual = null;
      if (!rodando) break;
      if (cfg.pausaMs) await new Promise((r) => { ciclo = setTimeout(r, cfg.pausaMs); });
    }
  }

  return {
    get running() { return rodando; },
    status() {
      return { running: rodando, ...estado, setup: checkSetup() };
    },
    start() {
      if (rodando) return { ok: true, already: true };
      const setup = checkSetup();
      if (!setup.ready) {
        return { ok: false, reason: `faltando: ${setup.missing.join(" e ")}`,
                 hint: setup.recorder_hint, setup };
      }
      fs.mkdirSync(tmpDir(), { recursive: true });
      rodando = true;
      estado.desde = Date.now();
      laco();
      return { ok: true, recorder: setup.recorder, custo: setup.custo };
    },
    async stop() {
      rodando = false;
      if (ciclo) { clearTimeout(ciclo); ciclo = null; }
      if (atual) { try { await atual; } catch {} }
      return { ok: true, ...estado };
    },
  };
}
