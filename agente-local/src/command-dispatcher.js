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
import { probeAll, speak } from "./tts.js";
import {
  checkSetup, detectWakeWord, loadSttConfig, MODELS, saveSttConfig, transcribe,
} from "./stt.js";
import {
  deleteVoiceSample, ENGINES, listVoiceSamples, loadVoiceConfig, RANGES,
  saveVoiceConfig, saveVoiceSample,
} from "./voice-config.js";

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

    // ---- voz (Seção 14) ----
    // Não passa pelo gate de tier: falar, transcrever e ajustar a própria voz não
    // toca em arquivo do usuário nem executa programa. É a mesma razão pela qual
    // "chat" não pede confirmação. Escrever amostra de voz fica dentro da pasta
    // do agente (~/.jarvis-agente/voices), fora das allowed_roots.
    if (VOICE_ACTIONS.has(action)) {
      return handleVoice(action, msg.args || {});
    }

    return { ok: false, data: { error: `ação desconhecida: ${action}` } };
  };
}

const VOICE_ACTIONS = new Set([
  "voice_status", "voice_config_get", "voice_config_set",
  "voice_list_samples", "voice_save_sample", "voice_delete_sample",
  "tts_speak", "stt_transcribe", "stt_config_get", "stt_config_set",
]);

async function handleVoice(action, args) {
  try {
    switch (action) {
      case "voice_status": {
        const [motores, cfg] = [await probeAll(), loadVoiceConfig()];
        return { ok: true, data: {
          engines: motores,
          config: cfg,
          samples: listVoiceSamples(),
          stt: checkSetup(),
          ranges: RANGES,
          engines_disponiveis: ENGINES,
          stt_models: MODELS,
        } };
      }
      case "voice_config_get":
        return { ok: true, data: { config: loadVoiceConfig(), ranges: RANGES } };
      case "voice_config_set":
        // saveVoiceConfig sanitiza: valor fora da faixa é preso no limite
        return { ok: true, data: { config: saveVoiceConfig(args) } };

      case "voice_list_samples":
        return { ok: true, data: { samples: listVoiceSamples() } };
      case "voice_save_sample": {
        // O áudio chega em base64 pelo WS. O agente é sempre cliente (Seção 8),
        // então é assim que um arquivo desce até ele — nunca abrindo porta.
        const bruto = String(args.data_base64 || "");
        if (!bruto) return { ok: false, data: { error: "sem data_base64" } };
        const buf = Buffer.from(bruto, "base64");
        if (!buf.length) return { ok: false, data: { error: "base64 inválido" } };
        if (buf.length > MAX_SAMPLE_BYTES) {
          return { ok: false, data: {
            error: `amostra grande demais (${buf.length} bytes, máx ${MAX_SAMPLE_BYTES})` } };
        }
        return { ok: true, data: { saved: saveVoiceSample(args.name, buf) } };
      }
      case "voice_delete_sample":
        return { ok: true, data: { deleted: deleteVoiceSample(args.name) } };

      case "tts_speak": {
        const r = await speak(args.text, args.overrides || {});
        if (!r.ok) return { ok: false, data: r };
        // áudio volta em base64 pelo mesmo caminho do WS
        return { ok: true, data: {
          engine: r.engine, fallback: r.fallback, mime: r.mime, bytes: r.bytes,
          audio_base64: r.audio.toString("base64"),
        } };
      }

      case "stt_config_get":
        return { ok: true, data: { config: loadSttConfig(), setup: checkSetup(), models: MODELS } };
      case "stt_config_set":
        return { ok: true, data: { config: saveSttConfig(args) } };
      case "stt_transcribe": {
        const r = await transcribe(args.path, args.overrides || {});
        if (!r.ok) return { ok: false, data: r };
        return { ok: true, data: { text: r.text, model: r.model,
                                   wake: detectWakeWord(r.text) } };
      }
      default:
        return { ok: false, data: { error: `ação de voz desconhecida: ${action}` } };
    }
  } catch (err) {
    return { ok: false, data: { error: String(err?.message || err) } };
  }
}

// Amostra de referência de voz são poucos segundos. Teto evita alguém empurrar
// um arquivo enorme pelo WebSocket.
const MAX_SAMPLE_BYTES = 8 * 1024 * 1024;
