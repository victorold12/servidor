/**
 * Máquina de decisão + execução SEM shell. Une o validador (tier-validator.js)
 * à execução real, aplicando o gate das 4 camadas antes de rodar qualquer coisa.
 *
 * Fronteira de responsabilidade (importante):
 *   - AQUI (segurança): decidir se roda, se pergunta, ou se bloqueia; e rodar
 *     sempre com array de args e shell:false (Seção 9).
 *   - INJETADO (`confirmFn`): a janela/notificação NATIVA de confirmação local
 *     (Seção 7). O diálogo é do sistema operacional e é plugado por fora — mas
 *     a REGRA de quando ele aparece é definida aqui e não pode ser pulada.
 *
 * O backend nunca chama isto diretamente: o agente recebe o comando pelo WS,
 * passa por aqui, e só então (talvez) executa. O backend é mensageiro (Seção 0).
 */
import { execFile } from "node:child_process";
import {
  TIER,
  classifyCommand,
  parseCommand,
  tierName,
} from "./tier-validator.js";

/**
 * @param {object} opts
 * @param {string} opts.command           comando cru pedido pelo modelo/backend
 * @param {string[]} [opts.allowedRoots]   pastas permitidas (contexto de auditoria)
 * @param {(info:object)=>Promise<"once"|"always"|"deny">} [opts.confirmFn]
 *        levanta a confirmação NATIVA local pra Tier 2 e resolve com a escolha.
 *        Ausente => qualquer Tier 2 é negado (fail-safe: sem UI, não roda).
 * @param {(action:string)=>boolean} [opts.isUnlocked]
 *        consulta se um item Tier 3 foi liberado explicitamente nas configs.
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

  // Tier 3 — bloqueio duro. Só passa se liberado item a item nas configs (Seção 6).
  if (tier === TIER.BLOCK) {
    if (!isUnlocked(command)) {
      return fail("denied", tier, baseAudit, `bloqueado: ${reason}`);
    }
  }

  // Tier 2 — confirmação local out-of-band. Sem confirmFn, nega (fail-safe).
  let decision = "auto";
  if (tier === TIER.CONFIRM) {
    if (!confirmFn) {
      return fail("denied", tier, baseAudit, "Tier 2 sem canal de confirmação local");
    }
    const choice = await confirmFn({
      command,               // comando CRU, exato — a última defesa é você ler isto
      reason,
      tier,
      tierLabel: tierName(tier),
      provenance,
    });
    if (choice === "deny") return fail("denied", tier, baseAudit, "negado na confirmação local");
    decision = choice === "always" ? "confirmed-always" : "confirmed";
  }

  // Parse sem shell. Se veio metacaractere, parseCommand devolve null — nunca
  // caímos pra `shell:true`; isso seria reabrir o vetor de injeção (Seção 9).
  const argv = parseCommand(command);
  if (!argv) {
    return fail("denied", tier, baseAudit, "comando exige shell — recusado por segurança");
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
