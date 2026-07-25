/**
 * Preferências de voz do JARVIS — motor, voz escolhida e calibração.
 *
 * Seção 14 do prompt mestre: Chatterbox é o principal (clona voz a partir de uma
 * amostra), Kokoro é o fallback (vozes prontas). O usuário escolhe e calibra na
 * aba de configuração; isto aqui é onde a escolha mora no PC.
 *
 * Fica separado do config.json do pareamento de propósito: aquele arquivo tem o
 * vínculo com o backend e não deve ser reescrito a cada vez que se arrasta um
 * slider de voz.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DIR = path.join(os.homedir(), ".jarvis-agente");
const FILE = path.join(DIR, "voice.json");
export const VOICES_DIR = path.join(DIR, "voices");

/** Motores possíveis. `navegador` existe pro caso de não haver nada local. */
export const ENGINES = ["chatterbox", "kokoro", "navegador"];

/**
 * Faixas de calibração. Os dois primeiros são os parâmetros reais do Chatterbox:
 * `exaggeration` mexe na intensidade emocional e `cfg_weight` no quanto o modelo
 * segue a referência (menor = mais solto, fala mais rápido).
 */
export const RANGES = {
  exaggeration: { min: 0.25, max: 2.0, default: 0.5 },
  cfg_weight:   { min: 0.0,  max: 1.0, default: 0.5 },
  temperature:  { min: 0.05, max: 1.5, default: 0.8 },
  speed:        { min: 0.5,  max: 2.0, default: 1.0 },  // Kokoro
};

export const DEFAULTS = {
  engine: "chatterbox",
  voice: null,               // amostra clonada (Chatterbox) ou voz pronta (Kokoro)
  chatterboxUrl: "http://127.0.0.1:8004",
  kokoroUrl: "http://127.0.0.1:8880",
  exaggeration: RANGES.exaggeration.default,
  cfg_weight: RANGES.cfg_weight.default,
  temperature: RANGES.temperature.default,
  speed: RANGES.speed.default,
  language: "pt",
};

function clamp(valor, faixa, padrao) {
  // null e "" precisam contar como "não informado". Number(null) é 0, então sem
  // esta guarda um campo vazio da interface viraria o mínimo da faixa em vez de
  // manter o valor atual.
  if (valor === null || valor === "" || typeof valor === "boolean") return padrao;
  const n = Number(valor);
  if (!Number.isFinite(n)) return padrao;
  return Math.min(faixa.max, Math.max(faixa.min, n));
}

/**
 * Normaliza o que veio de fora. Vale pra qualquer origem — a aba de config, um
 * comando do backend, um arquivo editado à mão: valor fora da faixa é ajustado
 * pro limite em vez de ir cru pro motor de TTS e virar áudio quebrado.
 */
export function sanitize(entrada = {}) {
  const base = { ...DEFAULTS, ...loadVoiceConfig() };
  const out = { ...base };

  if (ENGINES.includes(entrada.engine)) out.engine = entrada.engine;
  if (typeof entrada.voice === "string" || entrada.voice === null) {
    // nome de arquivo só: barra ou ".." aqui viraria leitura fora da pasta
    out.voice = entrada.voice ? path.basename(entrada.voice) : null;
  }
  for (const chave of ["chatterboxUrl", "kokoroUrl"]) {
    if (typeof entrada[chave] === "string" && /^https?:\/\//.test(entrada[chave])) {
      out[chave] = entrada[chave].replace(/\/+$/, "");
    }
  }
  for (const [chave, faixa] of Object.entries(RANGES)) {
    if (entrada[chave] !== undefined) out[chave] = clamp(entrada[chave], faixa, base[chave]);
  }
  if (typeof entrada.language === "string" && entrada.language.length <= 8) {
    out.language = entrada.language;
  }
  return out;
}

export function loadVoiceConfig() {
  try {
    return { ...DEFAULTS, ...JSON.parse(fs.readFileSync(FILE, "utf8")) };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveVoiceConfig(cfg) {
  fs.mkdirSync(DIR, { recursive: true });
  const limpo = sanitize(cfg);
  fs.writeFileSync(FILE, JSON.stringify(limpo, null, 2), { mode: 0o600 });
  return limpo;
}

/** Amostras de voz que o usuário subiu (as vozes clonáveis do Chatterbox). */
export function listVoiceSamples() {
  try {
    return fs.readdirSync(VOICES_DIR)
      .filter((f) => /\.(wav|mp3|flac|ogg|m4a)$/i.test(f))
      .map((f) => {
        const st = fs.statSync(path.join(VOICES_DIR, f));
        return { name: f, size: st.size, added_at: st.mtimeMs / 1000 };
      })
      .sort((a, b) => b.added_at - a.added_at);
  } catch {
    return [];
  }
}

export function voiceSamplePath(nome) {
  if (!nome) return null;
  const p = path.join(VOICES_DIR, path.basename(nome));
  return fs.existsSync(p) ? p : null;
}

export function saveVoiceSample(nome, buffer) {
  fs.mkdirSync(VOICES_DIR, { recursive: true });
  const seguro = path.basename(String(nome || "voz.wav")).replace(/[^\w.\-]/g, "_");
  const destino = path.join(VOICES_DIR, seguro);
  fs.writeFileSync(destino, buffer, { mode: 0o600 });
  return { name: seguro, size: buffer.length };
}

export function deleteVoiceSample(nome) {
  const p = voiceSamplePath(nome);
  if (!p) return false;
  fs.unlinkSync(p);
  const cfg = loadVoiceConfig();
  if (cfg.voice === path.basename(nome)) saveVoiceConfig({ ...cfg, voice: null });
  return true;
}
