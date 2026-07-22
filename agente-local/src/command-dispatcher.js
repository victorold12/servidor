/**
 * Traduz {type:"command", action, args, chat_id, message_id} (vindo do hub via
 * WS — Seção 12) numa chamada ao safe-exec, grava auditoria dupla, e devolve
 * o {ok, data} que o ws-client manda de volta como {type:"result"}.
 *
 * Escopo deliberado: só a ação "run" está ligada por ora. Ela já cobre leitura,
 * escrita e organização de arquivo via allowlist de comando (`dir`/`ls`/`cat`/
 * `mkdir`/`copy`/`move`/`ren` — Seção 6). Ações estruturadas de arquivo
 * (fs_read/fs_write direto via classifyPath, sem passar por shell) são um
 * incremento separado — tier-validator.js já expõe classifyPath pronto pra
 * quando isso entrar; não é feito aqui pra não misturar os dois no mesmo commit.
 */
import { runCommand } from "./safe-exec.js";
import { recordAudit } from "./audit.js";

/**
 * @param {object} deps
 * @param {()=>string[]} deps.getAllowedRoots
 * @param {(info:object)=>Promise<"once"|"always"|"deny">} deps.confirmFn
 * @param {(entry:object)=>void} [deps.sendAudit]  best-effort, ver audit.js
 * @param {(action:string)=>boolean} [deps.isUnlocked]
 * @param {string} [deps.auditFilePath]  injetável pra teste
 */
export function createCommandHandler({ getAllowedRoots, confirmFn, sendAudit, isUnlocked, auditFilePath }) {
  return async function handleCommand(msg) {
    if (msg?.action !== "run") {
      return { ok: false, data: { error: `ação desconhecida: ${msg?.action}` } };
    }
    const result = await runCommand({
      command: String(msg.args?.command || ""),
      allowedRoots: getAllowedRoots(),
      confirmFn,
      isUnlocked,
      provenance: { chat_id: msg.chat_id, message_id: msg.message_id },
    });
    recordAudit({ entry: result.audit, sendToHub: sendAudit, filePath: auditFilePath });
    return { ok: result.ok, data: { stdout: result.stdout, stderr: result.stderr, error: result.error } };
  };
}
