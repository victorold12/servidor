/**
 * STT local com whisper.cpp (Seções 2 e 9 do prompt mestre).
 *
 * Roda o binário do whisper.cpp num arquivo de áudio e devolve o texto. Modelo
 * padrão é `base`, não `large`: a Seção 9 fixa isso por RAM (~75-150 MB contra
 * vários GB), e trocar de modelo é escolha nas configurações.
 *
 * Execução sem shell, com argumentos em array — mesma regra do safe-exec.js
 * (Seção 8). Nome de arquivo com espaço, aspas ou `;` não vira comando.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DIR = path.join(os.homedir(), ".jarvis-agente");
const FILE = path.join(DIR, "stt.json");

export const MODELS = ["tiny", "base", "small", "medium", "large-v3"];

export const DEFAULTS = {
  binary: "whisper-cli",        // ou o caminho completo do main/whisper-cli
  model: "base",                // Seção 9: base por padrão, por causa da RAM
  modelsDir: path.join(DIR, "whisper-models"),
  language: "pt",
  threads: Math.max(2, Math.min(8, os.cpus().length)),
};

export function loadSttConfig() {
  try {
    return { ...DEFAULTS, ...JSON.parse(fs.readFileSync(FILE, "utf8")) };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveSttConfig(entrada = {}) {
  const base = loadSttConfig();
  const out = { ...base };
  if (typeof entrada.binary === "string" && entrada.binary.trim()) out.binary = entrada.binary.trim();
  if (MODELS.includes(entrada.model)) out.model = entrada.model;
  if (typeof entrada.modelsDir === "string" && entrada.modelsDir.trim()) out.modelsDir = entrada.modelsDir.trim();
  if (typeof entrada.language === "string" && entrada.language.length <= 8) out.language = entrada.language;
  const t = Number(entrada.threads);
  if (Number.isFinite(t)) out.threads = Math.max(1, Math.min(32, Math.floor(t)));

  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(out, null, 2), { mode: 0o600 });
  return out;
}

export function modelPath(cfg = loadSttConfig()) {
  return path.join(cfg.modelsDir, `ggml-${cfg.model}.bin`);
}

/** O que falta pro STT funcionar? A aba de config mostra isto ao usuário. */
export function checkSetup(cfg = loadSttConfig()) {
  const modelo = modelPath(cfg);
  const temModelo = fs.existsSync(modelo);
  return {
    model: cfg.model,
    model_path: modelo,
    model_present: temModelo,
    binary: cfg.binary,
    ready: temModelo,       // do binário só dá certeza tentando rodar
    hint: temModelo ? null
      : `baixe o modelo ggml-${cfg.model}.bin do whisper.cpp para ${cfg.modelsDir}`,
  };
}

function rodar(bin, args, timeoutMs) {
  return new Promise((resolve) => {
    let proc;
    try {
      // sem shell: argumentos vão como array (Seção 8)
      proc = spawn(bin, args, { shell: false, windowsHide: true });
    } catch (err) {
      resolve({ code: -1, stdout: "", stderr: String(err.message) });
      return;
    }
    let out = "", err = "";
    const timer = setTimeout(() => { try { proc.kill(); } catch {} }, timeoutMs);
    proc.stdout?.on("data", (d) => { out += d.toString(); });
    proc.stderr?.on("data", (d) => { err += d.toString(); });
    proc.on("error", (e) => {
      clearTimeout(timer);
      resolve({ code: -1, stdout: out, stderr: e.message });
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout: out, stderr: err });
    });
  });
}

/** Limpa a saída do whisper.cpp: tira os marcadores [00:00:00.000 --> ...]. */
export function parseTranscript(stdout) {
  return stdout
    .split("\n")
    .map((l) => l.replace(/^\s*\[[\d:.]+\s*-->\s*[\d:.]+\]\s*/, "").trim())
    .filter((l) => l && !l.startsWith("[") && !/^whisper_/.test(l))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Transcreve um arquivo de áudio. Devolve { ok, text } ou { ok:false, reason }.
 * Binário ausente é estado normal (o usuário pode não ter instalado), então
 * vira motivo legível em vez de exceção.
 */
export async function transcribe(audioPath, overrides = {}, timeoutMs = 120_000) {
  const cfg = { ...loadSttConfig(), ...overrides };

  if (!audioPath || !fs.existsSync(audioPath)) {
    return { ok: false, reason: "arquivo de áudio não encontrado" };
  }
  const modelo = modelPath(cfg);
  if (!fs.existsSync(modelo)) {
    return { ok: false, reason: `modelo do whisper não encontrado em ${modelo}`,
             hint: checkSetup(cfg).hint };
  }

  const args = [
    "-m", modelo,
    "-f", audioPath,
    "-l", cfg.language,
    "-t", String(cfg.threads),
    "-nt",                      // sem timestamps na saída
  ];
  const r = await rodar(cfg.binary, args, timeoutMs);

  if (r.code === -1) {
    return { ok: false, reason: `não consegui executar "${cfg.binary}" (${r.stderr})`,
             hint: "instale o whisper.cpp e aponte o caminho do binário nas configurações" };
  }
  if (r.code !== 0) {
    return { ok: false, reason: `whisper saiu com código ${r.code}`,
             detail: r.stderr.slice(-300) };
  }

  const texto = parseTranscript(r.stdout);
  if (!texto) return { ok: true, text: "", note: "áudio sem fala reconhecível" };
  return { ok: true, text: texto, model: cfg.model };
}

// ---------------------------------------------------------------- wake word
/**
 * Detecção da wake word ("Ei, JARVIS") sobre o texto transcrito.
 *
 * Sem modelo dedicado: o áudio já passa pelo whisper, e comparar o texto cobre o
 * caso de uso. Isto tolera o que a transcrição costuma errar — acento, "ei/hey",
 * e o nome vindo soletrado ("j a r v i s") ou junto.
 *
 * O que NÃO faz: escutar continuamente com custo zero, que é o que um
 * openWakeWord resolveria. Aqui cada trecho passa pelo whisper, então o loop de
 * escuta contínua gasta CPU. Está dito pra ninguém supor o contrário.
 */
const NOMES = ["jarvis", "jarvez", "jarves", "jarvis"];
const CHAMADAS = ["ei", "hey", "e", "oi", "ok", "opa"];

function normalizar(s) {
  return String(s || "")
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function detectWakeWord(texto) {
  const t = normalizar(texto);
  if (!t) return { hit: false };

  // "j a r v i s" soletrado vira "jarvis"
  const compacto = t.replace(/\b([a-z])\s(?=[a-z]\b)/g, "$1");

  for (const alvo of [t, compacto]) {
    for (const nome of NOMES) {
      const idx = alvo.indexOf(nome);
      if (idx < 0) continue;
      const antes = alvo.slice(Math.max(0, idx - 12), idx).trim().split(" ").pop() || "";
      const comChamada = CHAMADAS.includes(antes);
      // o resto da frase é o comando — "ei jarvis abre o chrome" -> "abre o chrome"
      const resto = alvo.slice(idx + nome.length).trim();
      return {
        hit: true,
        greeted: comChamada,        // veio com "ei/hey" na frente
        command: resto || null,
        matched: nome,
      };
    }
  }
  return { hit: false };
}
