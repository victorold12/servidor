/**
 * Traduz {type:"command", action, args, chat_id, message_id} (vindo do hub via
 * WS — Seção 12) numa chamada ao safe-exec, grava auditoria dupla, e devolve
 * o {ok, data} que o ws-client manda de volta como {type:"result"}.
 *
 * Ações suportadas:
 *   - "run"                          -> runCommand (comando de sistema, sem shell)
 *   - "fs_read" | "fs_list"          -> runFileOp (leitura — Tier 0 nas roots)
 *   - "fs_write" | "fs_mkdir"        -> runFileOp (escrita — Tier 1 nas roots)
 *   - "fs_delete"                    -> runFileOp (arquivo: Tier 1; pasta: Tier 2)
 *
 * As ações fs_* usam classifyPath (sandbox por caminho) em vez de allowlist de
 * comando — cobrem criar/ler/listar/apagar sem passar por shell (Seção 4/9).
 */
import { runCommand, runFileOp } from "./safe-exec.js";
import { recordAudit } from "./audit.js";

const FS_ACTIONS = new Set(["fs_read", "fs_list", "fs_write", "fs_mkdir", "fs_delete"]);

/**
 * @param {object} deps
 * @param {()=>string[]} deps.getAllowedRoots
 * @param {(info:object)=>Promise<"once"|"always"|"deny">} deps.confirmFn
 * @param {(entry:object)=>void} [deps.sendAudit]  best-effort, ver audit.js
 * @param {(action:string)=>boolean} [deps.isUnlocked]
 * @param {string} [deps.auditFilePath]  injetável pra teste
 */
export function createCommandHandler({ getAllowedRoots, confirmFn, sendAudit, isUnlocked, auditFilePath }) {
  // Cache de sessão "sempre permitir" (Tier 2) — vive enquanto o processo do
  // agente vive, some no restart (Seção 13.1: "na mesma sessão"). Um por
  // handler = um por conexão de agente. A chave é a AÇÃO EXATA; ver o comentário
  // de segurança em safe-exec.js (applyGate).
  const alwaysCache = new Set();

  return async function handleCommand(msg) {
    const action = msg?.action;
    const provenance = { chat_id: msg?.chat_id, message_id: msg?.message_id };

    if (action === "run") {
      const result = await runCommand({
        command: String(msg.args?.command || ""),
        allowedRoots: getAllowedRoots(),
        confirmFn,
        isUnlocked,
        alwaysCache,
        provenance,
      });
      recordAudit({ entry: result.audit, sendToHub: sendAudit, filePath: auditFilePath });
      return { ok: result.ok, data: { stdout: result.stdout, stderr: result.stderr, error: result.error } };
    }

    if (FS_ACTIONS.has(action)) {
      const op = action.slice(3); // "read" | "list" | "write" | "mkdir" | "delete"
      const result = await runFileOp({
        op,
        path: String(msg.args?.path || ""),
        content: msg.args?.content,
        allowedRoots: getAllowedRoots(),
        confirmFn,
        alwaysCache,
        provenance,
      });
      recordAudit({ entry: result.audit, sendToHub: sendAudit, filePath: auditFilePath });
      return {
        ok: result.ok,
        data: {
          stdout: result.stdout,
          error: result.error,
          // metadados úteis pro modelo/painel entenderem o resultado sem re-ler
          truncated: result.truncated,
          bytes: result.bytes,
          count: result.count,
        },
      };
    }

    return { ok: false, data: { error: `ação desconhecida: ${action}` } };
  };
}
