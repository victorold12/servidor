/**
 * Máquina de decisão + execução SEM shell. Une o validador (tier-validator.js)
 * à execução real, aplicando o gate das 4 camadas antes de rodar qualquer coisa.
 *
 * Duas portas de entrada:
 *   - runCommand: comando de sistema (execFile, shell:false — Seção 9).
 *   - runFileOp:  ação de arquivo estruturada (fs direto, sem passar por shell)
 *     usando classifyPath — cobre criar/ler/listar/apagar arquivo e pasta
 *     dentro das roots (Seção 4, Tier 1). Ambas passam pelo MESMO gate
 *     (applyGate) — uma regra de tier só, sem divergência entre os caminhos.
 *
 * Fronteira de responsabilidade (importante):
 *   - AQUI (segurança): decidir se roda, se pergunta, ou se bloqueia; e rodar
 *     sempre com array de args e shell:false (Seção 9), ou fs sem shell.
 *   - INJETADO (`confirmFn`): a janela/notificação NATIVA de confirmação local
 *     (Seção 7). O diálogo é do sistema operacional e é plugado por fora — mas
 *     a REGRA de quando ele aparece é definida aqui e não pode ser pulada.
 *
 * O backend nunca chama isto diretamente: o agente recebe o comando pelo WS,
 * passa por aqui, e só então (talvez) executa. O backend é mensageiro (Seção 0).
 */
import { execFile } from "node:child_process";
import fsp from "node:fs/promises";
import path from "node:path";
import {
  TIER,
  classifyCommand,
  classifyPath,
  parseCommand,
  tierName,
} from "./tier-validator.js";

const MAX_READ_BYTES = 200_000;    // teto do que fs_read devolve (evita WS gigante)
const MAX_WRITE_BYTES = 2_000_000; // teto do que fs_write aceita
const MAX_LIST_ENTRIES = 1000;

/**
 * Gate das 4 camadas — a ÚNICA regra de decisão, compartilhada por comando e
 * arquivo. Não executa nada, só decide: { allowed, decision, error? }.
 *
 * Cache de sessão "sempre permitir" (Seção 13.1, absorvido do rezaulhreza/jarvis):
 * quando o usuário escolhe "always" numa confirmação Tier 2, a MESMA ação não
 * pergunta de novo no resto da sessão (o `alwaysCache` some quando o processo
 * do agente reinicia).
 *
 * DECISÃO DE SEGURANÇA DELIBERADA — a chave do cache é a AÇÃO EXATA, não o
 * "tipo" solto:
 *   - comando: o comando cru normalizado INTEIRO (`run:<cmd>`), não só o nome do
 *     programa. Se fosse por programa, liberar "sempre" o `foo` deixaria um
 *     site malicioso (o backend é tratado como comprometido — Seção 0) injetar
 *     `foo <args destrutivos>` sem nova confirmação. Chave exata fecha essa
 *     escalada e ainda cumpre o objetivo (não repetir a MESMA pergunta).
 *   - arquivo: `fs_<op>:<caminho canônico>` — "sempre" vale só pra aquele
 *     arquivo/pasta exato, nunca "sempre escrever em qualquer lugar".
 * Tier 3 é tratado ANTES do cache e nunca chega aqui — "always" jamais libera
 * destrutivo (Seção 6).
 */
async function applyGate({ tier, reason, confirmFn, isUnlocked, unlockKey, confirmInfo, alwaysCache, cacheKey }) {
  if (tier === TIER.BLOCK) {
    if (!isUnlocked(unlockKey)) {
      return { allowed: false, decision: "denied", error: `bloqueado: ${reason}` };
    }
    return { allowed: true, decision: "auto" };
  }

  if (tier === TIER.CONFIRM) {
    if (alwaysCache && cacheKey && alwaysCache.has(cacheKey)) {
      return { allowed: true, decision: "confirmed-always-cache" };
    }
    if (!confirmFn) {
      return { allowed: false, decision: "denied", error: "Tier 2 sem canal de confirmação local" };
    }
    const choice = await confirmFn(confirmInfo);
    if (choice === "deny") return { allowed: false, decision: "denied", error: "negado na confirmação local" };
    if (choice === "always" && alwaysCache && cacheKey) alwaysCache.add(cacheKey);
    return { allowed: true, decision: choice === "always" ? "confirmed-always" : "confirmed" };
  }

  return { allowed: true, decision: "auto" };
}

/**
 * @param {object} opts
 * @param {string} opts.command           comando cru pedido pelo modelo/backend
 * @param {string[]} [opts.allowedRoots]   pastas permitidas (contexto de auditoria)
 * @param {(info:object)=>Promise<"once"|"always"|"deny">} [opts.confirmFn]
 *        levanta a confirmação NATIVA local pra Tier 2 e resolve com a escolha.
 *        Ausente => qualquer Tier 2 é negado (fail-safe: sem UI, não roda).
 * @param {(action:string)=>boolean} [opts.isUnlocked]
 *        consulta se um item Tier 3 foi liberado explicitamente nas configs.
 * @param {Set<string>} [opts.alwaysCache]  cache de sessão "sempre permitir".
 * @param {object} [opts.provenance]       { chat_id, message_id } pra auditoria
 * @param {number} [opts.timeoutMs]
 * @returns {Promise<{ok:boolean, decision:string, tier:number, audit:object, stdout?:string, stderr?:string, error?:string}>}
 */
export async function runCommand(opts) {
  const {
    command,
    allowedRoots = [],
    confirmFn = null,
    isUnlocked = () => false,
    alwaysCache = null,
    provenance = {},
    timeoutMs = 60_000,
  } = opts;

  const { tier, reason } = classifyCommand(command);
  const baseAudit = {
    action_type: "run",
    target: command,
    tier,
    chat_id: provenance.chat_id ?? null,
    message_id: provenance.message_id ?? null,
    ts: Date.now() / 1000,
  };

  const gate = await applyGate({
    tier,
    reason,
    confirmFn,
    isUnlocked,
    unlockKey: command,
    // comando CRU, exato — a última defesa é o usuário ler isto na janela nativa
    confirmInfo: { command, reason, tier, tierLabel: tierName(tier), provenance },
    alwaysCache,
    cacheKey: `run:${String(command).trim().replace(/\s+/g, " ")}`,
  });
  if (!gate.allowed) return fail(gate.decision, tier, baseAudit, gate.error);
  const decision = gate.decision;

  // Parse sem shell. Se veio metacaractere, parseCommand devolve null — nunca
  // caímos pra `shell:true`; isso seria reabrir o vetor de injeção (Seção 9).
  // Roda mesmo se o gate liberou por cache: o cache pula a PERGUNTA, não esta
  // defesa — um comando com shell continua recusado aqui.
  const argv = parseCommand(command);
  if (!argv) {
    return fail(decision, tier, baseAudit, "comando exige shell — recusado por segurança");
  }

  try {
    const { stdout, stderr } = await execFileAsync(argv[0], argv.slice(1), timeoutMs);
    return {
      ok: true,
      decision,
      tier,
      stdout,
      stderr,
      audit: { ...baseAudit, decision, result: "ok" },
    };
  } catch (err) {
    const msg = String(err?.message || err).slice(0, 300);
    return {
      ok: false,
      decision,
      tier,
      error: msg,
      audit: { ...baseAudit, decision, result: `error:${msg}` },
    };
  }
}

const FILE_OPS = new Set(["read", "list", "write", "mkdir", "delete", "organize"]);

/* Categorias do "organizar pasta". Extensão desconhecida NÃO é movida: mexer no
   que não se reconhece é como o assistente perde a confiança do usuário — ele
   volta e não acha o arquivo. Fica onde está e entra no relatório. */
const CATEGORIAS = [
  ["Documentos", ["pdf","doc","docx","odt","rtf","txt","md","epub"]],
  ["Planilhas",  ["xls","xlsx","csv","ods","tsv"]],
  ["Slides",     ["ppt","pptx","odp"]],
  ["Imagens",    ["jpg","jpeg","png","gif","webp","bmp","svg","heic","avif","tiff","ico"]],
  ["Videos",     ["mp4","mkv","avi","mov","wmv","webm","m4v","flv"]],
  ["Audio",      ["mp3","wav","flac","m4a","aac","ogg","wma","opus"]],
  ["Compactados",["zip","rar","7z","tar","gz","xz","bz2"]],
  ["Programas",  ["exe","msi","bat","cmd","ps1","sh","appimage","deb","rpm","dmg"]],
  ["Codigo",     ["js","ts","py","java","c","cpp","cs","go","rs","rb","php","html","css","json","xml","yml","yaml","sql","ipynb"]],
];
function categoriaDe(nome) {
  const ext = nome.includes(".") ? nome.split(".").pop().toLowerCase() : "";
  if (!ext) return null;
  const achou = CATEGORIAS.find(([, exts]) => exts.includes(ext));
  return achou ? achou[0] : null;
}

/* Nome livre no destino: "nota.pdf" que colide vira "nota (2).pdf".
   Sobrescrever silenciosamente seria destruir arquivo numa operação que o
   usuário pediu como ARRUMAR. */
async function nomeLivre(destDir, nome) {
  const ponto = nome.lastIndexOf(".");
  const base = ponto > 0 ? nome.slice(0, ponto) : nome;
  const ext = ponto > 0 ? nome.slice(ponto) : "";
  for (let i = 1; i < 500; i++) {
    const tentativa = i === 1 ? nome : `${base} (${i})${ext}`;
    try {
      await fsp.access(path.join(destDir, tentativa));
    } catch {
      return tentativa;                       // não existe: pode usar
    }
  }
  throw new Error(`não achei nome livre para ${nome}`);
}

/**
 * Ação de arquivo estruturada — sem shell, classificada por classifyPath
 * (sandbox + canonicaliza `..`/symlink + denylist de segredo). Cobre Tier 1
 * (criar/ler/listar/apagar dentro das roots) da Seção 4.
 *
 * @param {object} opts
 * @param {"read"|"list"|"write"|"mkdir"|"delete"} opts.op
 * @param {string} opts.path               caminho pedido (pode ter ~, .., não existir)
 * @param {string} [opts.content]          conteúdo pra "write"
 * @param {string[]} [opts.allowedRoots]
 * @param {(info:object)=>Promise<"once"|"always"|"deny">} [opts.confirmFn]
 * @param {Set<string>} [opts.alwaysCache]
 * @param {object} [opts.provenance]
 */
export async function runFileOp(opts) {
  const {
    op,
    path: rawPath,
    content = "",
    allowedRoots = [],
    confirmFn = null,
    alwaysCache = null,
    provenance = {},
  } = opts;

  const baseAuditSkeleton = {
    action_type: `fs_${op}`,
    chat_id: provenance.chat_id ?? null,
    message_id: provenance.message_id ?? null,
    ts: Date.now() / 1000,
  };

  if (!FILE_OPS.has(op)) {
    const baseAudit = { ...baseAuditSkeleton, target: String(rawPath || ""), tier: TIER.CONFIRM };
    return fail("denied", TIER.CONFIRM, baseAudit, `operação de arquivo desconhecida: ${op}`);
  }

  const mode = op === "read" || op === "list" ? "read" : "write";
  // organize mexe em vários arquivos de uma vez: classifica como escrita.
  let { tier, reason, canonical } = classifyPath(rawPath, allowedRoots, mode);

  // Apagar PASTA é destrutivo (recursivo) — sobe pra confirmação mesmo dentro
  // das roots. Apagar um arquivo só segue Tier 1 (WRITE) como o resto.
  if (op === "delete" && tier === TIER.WRITE) {
    try {
      const st = await fsp.stat(canonical);
      if (st.isDirectory()) {
        tier = TIER.CONFIRM;
        reason = "apagar pasta (conteúdo recursivo) — confirmar";
      }
    } catch {
      // não existe -> deixa a execução falhar com ENOENT (erro honesto), não
      // inventa um tier diferente.
    }
  }

  const baseAudit = { ...baseAuditSkeleton, target: canonical || String(rawPath || ""), tier };

  const gate = await applyGate({
    tier,
    reason,
    confirmFn,
    isUnlocked: () => false, // ação de arquivo nunca chega em Tier 3 via classifyPath
    unlockKey: canonical,
    confirmInfo: {
      command: `${op.toUpperCase()} ${canonical}`, // confirm.js mostra isto como "comando/ação exata"
      reason,
      tier,
      tierLabel: tierName(tier),
      provenance,
    },
    alwaysCache,
    cacheKey: `fs_${op}:${canonical}`,
  });
  if (!gate.allowed) return fail(gate.decision, tier, baseAudit, gate.error);
  const decision = gate.decision;

  try {
    const data = await execFileOp(op, canonical, content);
    return { ok: true, decision, tier, ...data, audit: { ...baseAudit, decision, result: "ok" } };
  } catch (err) {
    const msg = String(err?.message || err).slice(0, 300);
    return { ok: false, decision, tier, error: msg, audit: { ...baseAudit, decision, result: `error:${msg}` } };
  }
}

async function execFileOp(op, canonical, content) {
  if (op === "read") {
    const buf = await fsp.readFile(canonical);
    const truncated = buf.length > MAX_READ_BYTES;
    return { stdout: buf.subarray(0, MAX_READ_BYTES).toString("utf8"), truncated, bytes: buf.length };
  }
  if (op === "list") {
    const entries = await fsp.readdir(canonical, { withFileTypes: true });
    const items = entries.slice(0, MAX_LIST_ENTRIES).map((e) => ({ name: e.name, dir: e.isDirectory() }));
    return { stdout: JSON.stringify(items), count: entries.length };
  }
  if (op === "write") {
    const buf = Buffer.from(String(content), "utf8");
    if (buf.length > MAX_WRITE_BYTES) {
      throw new Error(`conteúdo grande demais (${buf.length} > ${MAX_WRITE_BYTES} bytes)`);
    }
    await fsp.mkdir(path.dirname(canonical), { recursive: true });
    await fsp.writeFile(canonical, buf, { mode: 0o600 });
    return { stdout: `escrito: ${canonical} (${buf.length} bytes)` };
  }
  if (op === "mkdir") {
    await fsp.mkdir(canonical, { recursive: true });
    return { stdout: `pasta criada: ${canonical}` };
  }
  if (op === "delete") {
    // force:false -> apagar o que não existe vira ENOENT (erro honesto). Tier 2
    // já cobriu o caso de pasta recursiva (gate acima), então recursive aqui é
    // seguro: só chega neste ponto quem passou pelo gate.
    await fsp.rm(canonical, { recursive: true, force: false });
    return { stdout: `apagado: ${canonical}` };
  }
  if (op === "organize") return organizarPasta(canonical);
  throw new Error(`op não implementada: ${op}`);
}

/* Arruma UMA pasta movendo os arquivos pra subpastas por tipo.
 *
 * Três regras que definem se isto é útil ou assustador:
 *
 *   1. Só o primeiro nível. Não desce em subpasta — "organizar Downloads" não
 *      pode virar uma varredura no projeto que estava lá dentro.
 *   2. Nada é apagado nem sobrescrito. Colisão de nome vira "arquivo (2).pdf".
 *      A operação é MOVER, e mover pode ser desfeito olhando o relatório.
 *   3. Extensão desconhecida fica onde está. Mexer no que não se reconhece é
 *      como o usuário volta e não acha o arquivo dele.
 *
 * Devolve um relatório do que aconteceu — sem ele, o usuário fica sabendo que
 * "organizou" e não o quê.
 */
async function organizarPasta(canonical) {
  const st = await fsp.stat(canonical);
  if (!st.isDirectory()) throw new Error(`não é uma pasta: ${canonical}`);

  const entradas = await fsp.readdir(canonical, { withFileTypes: true });
  const movidos = {};
  const ignorados = [];
  let total = 0;

  for (const e of entradas) {
    if (total >= MAX_LIST_ENTRIES) break;              // pasta gigante: para e reporta
    if (e.isDirectory()) continue;                     // regra 1
    if (!e.isFile()) continue;                         // link/socket: não é nosso caso
    const categoria = categoriaDe(e.name);
    if (!categoria) { ignorados.push(e.name); continue; }   // regra 3

    const destDir = path.join(canonical, categoria);
    await fsp.mkdir(destDir, { recursive: true });
    const destNome = await nomeLivre(destDir, e.name);      // regra 2
    await fsp.rename(path.join(canonical, e.name), path.join(destDir, destNome));
    (movidos[categoria] = movidos[categoria] || []).push(destNome);
    total += 1;
  }

  const resumo = Object.entries(movidos)
    .map(([cat, arqs]) => `${cat}: ${arqs.length}`)
    .join(", ") || "nada pra mover";
  return {
    stdout: JSON.stringify({ pasta: canonical, movidos, ignorados: ignorados.slice(0, 50),
                             total, resumo }),
    count: total,
  };
}

function fail(decision, tier, baseAudit, error) {
  return { ok: false, decision, tier, error, audit: { ...baseAudit, decision, result: `error:${error}` } };
}

function execFileAsync(file, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    execFile(file, args, { shell: false, timeout: timeoutMs, windowsHide: true }, (err, stdout, stderr) => {
      if (err) reject(err);
      else resolve({ stdout, stderr });
    });
  });
}
