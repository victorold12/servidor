/**
 * Escrita dupla de auditoria (Seção 10): local primeiro, sempre — sobrevive
 * mesmo se o WS estiver caído ou o backend estiver fora do ar — e espelhada
 * pro hub quando há conexão. Um backend comprometido não apaga silenciosamente
 * o que o agente fez, porque a cópia local continua existindo.
 *
 * Formato: JSON Lines (uma linha por evento) — append-only, fácil de inspecionar.
 *
 * Cadeia de hash (Seção 13.1, absorvido do JarvisAI): cada linha guarda
 * `prev_hash` (hash da linha anterior; a 1ª aponta pro genesis) e `hash` =
 * SHA-256(canonical(linha + prev_hash)). Adulterar, reordenar ou apagar
 * qualquer linha quebra verifyLocalChain(). Esta cadeia é INDEPENDENTE da do
 * backend (arquivo local vs tabela) — cada uma íntegra por si; o hub recebe o
 * evento cru e monta a própria cadeia do lado dele.
 */
import fs from "node:fs";
import crypto from "node:crypto";
import { auditLogPath } from "./config.js";

const GENESIS = "0".repeat(64);

// Último hash gravado por arquivo, nesta sessão — evita reler o arquivo inteiro
// a cada append. Cache miss (1º append da sessão) cai na leitura da última linha.
const _lastHash = new Map();

/** Serialização determinística: chaves ordenadas recursivamente, sem espaço.
 * Precisa ser idêntica na escrita e na verificação — nada de depender da ordem
 * de inserção do objeto. */
function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(stableStringify).join(",") + "]";
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + stableStringify(value[k])).join(",") + "}";
}

/** Hash de um registro (que já inclui prev_hash), excluindo o próprio campo hash. */
function hashRecord(record) {
  const { hash, ...rest } = record;
  return crypto.createHash("sha256").update(stableStringify(rest)).digest("hex");
}

function lastHashOf(filePath) {
  if (_lastHash.has(filePath)) return _lastHash.get(filePath);
  let prev = GENESIS;
  try {
    const raw = fs.readFileSync(filePath, "utf8");
    const lines = raw.split("\n").filter(Boolean);
    if (lines.length) {
      const last = JSON.parse(lines[lines.length - 1]);
      if (last && typeof last.hash === "string") prev = last.hash;
    }
  } catch {
    // arquivo não existe ainda -> começa do genesis
  }
  _lastHash.set(filePath, prev);
  return prev;
}

export function appendLocalAudit(entry, filePath = auditLogPath()) {
  const prev_hash = lastHashOf(filePath);
  const record = { ...entry, logged_at: Date.now() / 1000, prev_hash };
  record.hash = hashRecord(record);
  fs.appendFileSync(filePath, JSON.stringify(record) + "\n", { mode: 0o600 });
  _lastHash.set(filePath, record.hash);
}

export function readLocalAudit(limit = 100, filePath = auditLogPath()) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch {
    return [];
  }
  const lines = raw.split("\n").filter(Boolean);
  return lines.slice(-limit).map((l) => JSON.parse(l));
}

/**
 * Confere a cadeia de hash do log local inteiro (Seção 13.1). Linhas antigas
 * sem hash (pré-cadeia) formam um prefixo legado — puladas; a cadeia real
 * começa da 1ª linha com hash, escrita apontando pro genesis. Qualquer
 * adulteração/reordenação/remoção no trecho encadeado é detectada.
 * @returns {{ok:boolean, count:number, chained:number, legacy:number, brokenAt?:number}}
 */
export function verifyLocalChain(filePath = auditLogPath()) {
  let lines;
  try {
    lines = fs.readFileSync(filePath, "utf8").split("\n").filter(Boolean);
  } catch {
    return { ok: true, count: 0, chained: 0, legacy: 0 };
  }
  let prev = GENESIS;
  let chained = 0;
  let legacy = 0;
  for (let i = 0; i < lines.length; i++) {
    let rec;
    try {
      rec = JSON.parse(lines[i]);
    } catch {
      return { ok: false, count: lines.length, chained, legacy, brokenAt: i };
    }
    if (typeof rec.hash !== "string") {
      legacy++;
      continue;
    }
    if (rec.prev_hash !== prev || rec.hash !== hashRecord(rec)) {
      return { ok: false, count: lines.length, chained, legacy, brokenAt: i };
    }
    prev = rec.hash;
    chained++;
  }
  return { ok: true, count: lines.length, chained, legacy };
}

/**
 * @param {object} opts
 * @param {object} opts.entry              linha de auditoria (mesmo shape do audit_log do backend)
 * @param {(entry:object)=>void} [opts.sendToHub]  ex.: wsConnection.sendAudit — best-effort
 * @param {string} [opts.filePath]         injetável pra teste
 */
export function recordAudit({ entry, sendToHub, filePath }) {
  appendLocalAudit(entry, filePath);
  try {
    // Manda o evento CRU pro hub — o backend monta a própria cadeia. Não envia
    // o hash local (as duas cadeias são independentes por design).
    sendToHub?.(entry);
  } catch {
    // Já persistiu local — falha no envio remoto (WS caído, etc.) não perde o
    // registro. É exatamente essa a garantia da escrita dupla (Seção 10).
  }
}
