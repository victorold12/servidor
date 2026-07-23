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

const FILE_OPS = new Set(["read", "list", "write", "mkdir", "delete"]);

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
  throw new Error(`op não implementada: ${op}`);
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
