/**
 * Escrita dupla de auditoria (Seção 10): local primeiro, sempre — sobrevive
 * mesmo se o WS estiver caído ou o backend estiver fora do ar — e espelhada
 * pro hub quando há conexão. Um backend comprometido não apaga silenciosamente
 * o que o agente fez, porque a cópia local continua existindo.
 *
 * Formato: JSON Lines (uma linha por evento) — append-only, fácil de inspecionar.
 */
import fs from "node:fs";
import { auditLogPath } from "./config.js";

export function appendLocalAudit(entry, filePath = auditLogPath()) {
  const line = JSON.stringify({ ...entry, logged_at: Date.now() / 1000 }) + "\n";
  fs.appendFileSync(filePath, line, { mode: 0o600 });
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
 * @param {object} opts
 * @param {object} opts.entry              linha de auditoria (mesmo shape do audit_log do backend)
 * @param {(entry:object)=>void} [opts.sendToHub]  ex.: wsConnection.sendAudit — best-effort
 * @param {string} [opts.filePath]         injetável pra teste
 */
export function recordAudit({ entry, sendToHub, filePath }) {
  appendLocalAudit(entry, filePath);
  try {
    sendToHub?.(entry);
  } catch {
    // Já persistiu local — falha no envio remoto (WS caído, etc.) não perde o
    // registro. É exatamente essa a garantia da escrita dupla (Seção 10).
  }
}
