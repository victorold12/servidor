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
import os from "node:os";
import path from "node:path";
import fsp from "node:fs/promises";
import { execFile } from "node:child_process";
import { runCommand, runFileOp } from "./safe-exec.js";
import { recordAudit } from "./audit.js";
import { abreApp, carregaApps, fechaApp, precisaConfirmar, resolveApp, varreApps } from "./apps.js";
import { apagaAtalho, carregaAtalhos, resolveAtalho, salvaAtalho } from "./atalhos.js";
import { consulta as consultaAprovacao, registra as registraAprovacao } from "./aprovacoes.js";
import { probeAll, speak } from "./tts.js";
import {
  checkSetup, detectWakeWord, loadSttConfig, MODELS, saveSttConfig, transcribe,
} from "./stt.js";
import {
  deleteVoiceSample, ENGINES, listVoiceSamples, loadVoiceConfig, RANGES,
  saveVoiceConfig, saveVoiceSample,
} from "./voice-config.js";
import {
  checkSetup as checkListener, createListener, LIMITES as LISTENER_LIMITES,
  loadConfig as loadListenerConfig, RECORDERS, saveConfig as saveListenerConfig,
} from "./listener.js";

const FS_ACTIONS = new Set(["fs_read", "fs_list", "fs_write", "fs_mkdir", "fs_delete", "fs_organize"]);

/* Uso de CPU e memória. Tier 0 de verdade: só lê contadores do próprio sistema
   operacional, não toca em arquivo nem em rede, e não dá pra vazar nada com
   isso. Por isso não passa pelo gate de confirmação — perguntar "posso ver
   quanta RAM você tem?" a cada atualização deixaria a tela inutilizável. */
function metricasDoSistema() {
  const cpus = os.cpus();
  /* Percentual de CPU exige DOIS retratos: os contadores do SO são acumulados
     desde o boot, então um retrato sozinho daria a média da vida inteira da
     máquina — um número que nunca muda e não serve pra nada. */
  const agora = cpus.map((c) => {
    const t = c.times;
    return { ocupado: t.user + t.nice + t.sys + t.irq, total: t.user + t.nice + t.sys + t.irq + t.idle };
  });
  let usoCpu = null;
  if (metricasDoSistema._antes && metricasDoSistema._antes.length === agora.length) {
    let dOcupado = 0, dTotal = 0;
    agora.forEach((n, i) => {
      dOcupado += n.ocupado - metricasDoSistema._antes[i].ocupado;
      dTotal += n.total - metricasDoSistema._antes[i].total;
    });
    if (dTotal > 0) usoCpu = Math.max(0, Math.min(100, (dOcupado / dTotal) * 100));
  }
  metricasDoSistema._antes = agora;

  const totalMem = os.totalmem();
  const livreMem = os.freemem();
  return {
    cpu_pct: usoCpu === null ? null : Number(usoCpu.toFixed(1)),
    cpu_nucleos: cpus.length,
    cpu_modelo: cpus[0]?.model?.trim() || "",
    ram_total_bytes: totalMem,
    ram_usada_bytes: totalMem - livreMem,
    ram_pct: Number((((totalMem - livreMem) / totalMem) * 100).toFixed(1)),
    uptime_s: Math.round(os.uptime()),
    plataforma: `${os.platform()} ${os.release()}`,
    /* Na primeira chamada não há retrato anterior pra comparar. Dizer isso é
       melhor que devolver 0% e a pessoa achar que o PC está ocioso. */
    aviso: usoCpu === null ? "primeira leitura: o percentual de CPU aparece na próxima" : null,
  };
}

/* Só http/https. file:// abriria arquivo do PC sem passar pelas roots, e
   esquemas como javascript: ou ms-settings: viram execução disfarçada de
   "abrir link". A lista é fechada: o que não está aqui não abre. */
function urlSegura(bruta) {
  let u;
  try {
    u = new URL(String(bruta || ""));
  } catch {
    return null;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  return u.href;
}

/* Abre no navegador padrão SEM shell — o mesmo princípio do resto do agente.
   `start`/`open`/`xdg-open` com shell:true interpretaria a URL como linha de
   comando, e uma URL com & ou | viraria dois comandos. */
function abridorDoSistema(url) {
  if (process.platform === "win32") {
    // rundll32 em vez de `cmd /c start`: nenhum interpretador de comandos no meio.
    return { file: "rundll32", args: ["url.dll,FileProtocolHandler", url] };
  }
  if (process.platform === "darwin") return { file: "open", args: [url] };
  return { file: "xdg-open", args: [url] };
}

/**
 * @param {object} deps
 * @param {()=>string[]} deps.getAllowedRoots
 * @param {(info:object)=>Promise<"once"|"always"|"deny">} deps.confirmFn
 * @param {(entry:object)=>void} [deps.sendAudit]  best-effort, ver audit.js
 * @param {(action:string)=>boolean} [deps.isUnlocked]
 * @param {string} [deps.auditFilePath]  injetável pra teste
 */
/**
 * Envolve o `confirmFn` com a memória de aprovações (aprovacoes.js).
 *
 * POR QUE AQUI, E NÃO EM CADA PONTO DE CHAMADA
 *
 * `handleCommand` pergunta em cinco lugares diferentes (rodar, abrir link,
 * abrir/fechar app, atalho, arquivo). Ligar a memória em cada um significaria
 * cinco chances de esquecer — e o que se esquece num deles é justamente o que
 * volta a perguntar, sem ninguém entender por quê. Envolvendo uma vez, todos
 * herdam.
 *
 * O QUE ELA ACRESCENTA AO `alwaysCache` QUE JÁ EXISTIA
 *
 * O cache de sessão morre quando o agente reinicia — e o agente reinicia toda
 * vez que o PC liga. Na prática, "sempre permitir" durava até o fim do dia de
 * trabalho e a pergunta voltava na manhã seguinte. A memória persiste, com
 * prazo declarado e possibilidade de revogar.
 *
 * O que ela NÃO muda: Tier 3 continua bloqueado, e a decisão continua sendo
 * tomada no PC.
 */
function comMemoriaDeAprovacao(confirmFn) {
  /* Sem `confirmFn` não há como perguntar, e o gate trata isso como NEGAR.
     Envolver mesmo assim transformaria "não dá pra perguntar" em "chame
     undefined" — e uma memória de aprovação que altera o caminho de negação é
     exatamente o tipo de coisa que não pode acontecer aqui. */
  if (typeof confirmFn !== "function") return confirmFn;

  return async function confirmarLembrando(info) {
    const acao = {
      programa: info?.command || "",
      argumentos: [],
      escopo: info?.reason || "",
      tier: info?.tier,
      descricao: info?.command || "",
    };

    try {
      const ja = consultaAprovacao(acao);
      if (ja.aprovado) return "once";   // já autorizado antes; não perguntar de novo
    } catch { /* memória indisponível = perguntar, que é o padrão seguro */ }

    const decisao = await confirmFn(info);

    /* Só o "sempre" vira memória. "once" é uma autorização pontual, e
       transformá-la em permanente seria conceder mais do que foi pedido. */
    if (decisao === "always") {
      try { registraAprovacao(acao); } catch { /* não lembrar não pode derrubar a ação */ }
    }
    return decisao;
  };
}

export function createCommandHandler({ getAllowedRoots, confirmFn: confirmCru, sendAudit, isUnlocked, auditFilePath }) {
  const confirmFn = comMemoriaDeAprovacao(confirmCru);
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

    /* Leitura de contadores do próprio SO: não toca arquivo, não sai na rede,
       não tem o que confirmar. Fica FORA do gate de propósito. */
    if (action === "sys_metrics") {
      return { ok: true, data: metricasDoSistema() };
    }

    /* Abrir link no navegador. Passa pela confirmação local (Tier 2) quando o
       usuário não liberou antes: abrir página é barato pra quem pede e caro pra
       quem recebe — um link pode ser phishing, download, ou só invadir a tela
       de quem está no meio de outra coisa. A URL é validada ANTES de qualquer
       pergunta, pra não confirmar algo que ia falhar de todo jeito. */
    if (action === "open_url") {
      const url = urlSegura(msg.args?.url);
      const auditBase = { action_type: "open_url", target: String(msg.args?.url || ""),
                          tier: 2, ts: Date.now() / 1000, ...provenance };
      if (!url) {
        const erro = "só abro links http:// e https://";
        recordAudit({ entry: { ...auditBase, decision: "denied", result: `error:${erro}` },
                      sendToHub: sendAudit, filePath: auditFilePath });
        return { ok: false, data: { error: erro } };
      }
      const chave = `open_url:${new URL(url).origin}`;   // libera por SITE, não por link
      let decisao = alwaysCache.has(chave) ? "always" : null;
      if (!decisao) {
        decisao = await confirmFn({ command: `ABRIR ${url}`, reason: "abrir link no navegador",
                                    tier: 2, tierLabel: "confirmar", provenance });
        if (decisao === "always") alwaysCache.add(chave);
      }
      if (decisao === "deny") {
        recordAudit({ entry: { ...auditBase, decision: "deny", result: "error:negado no PC" },
                      sendToHub: sendAudit, filePath: auditFilePath });
        return { ok: false, data: { error: "você negou no PC" } };
      }
      const { file, args } = abridorDoSistema(url);
      const erro = await new Promise((resolve) =>
        execFile(file, args, { shell: false, timeout: 10000, windowsHide: true },
                 (err) => resolve(err ? String(err.message).slice(0, 200) : null)));
      recordAudit({ entry: { ...auditBase, decision: decisao, result: erro ? `error:${erro}` : "ok" },
                    sendToHub: sendAudit, filePath: auditFilePath });
      return erro ? { ok: false, data: { error: erro } } : { ok: true, data: { aberto: url } };
    }

    /* ====================================================================
       APLICATIVOS E ATALHOS

       Duas cercas, e as duas importam:

       1. Só roda o que está NO MAPA, e o mapa é feito aqui varrendo o disco.
          Um caminho que chega pelo WebSocket nunca vira processo por aqui —
          é o que separa "abrir um app" de "executar binário arbitrário".

       2. Abrir app comum é Tier 1 (automático, auditado): é o que a pessoa
          pediu, e o alvo saiu de uma lista local. Mas shell, editor de
          registro e agendador pedem confirmação mesmo estando no mapa —
          abrir um PowerShell não é abrir o Spotify. Fechar é sempre Tier 2:
          derrubar um programa pode custar trabalho não salvo, e isso é
          exatamente a definição de "suspeito" da Seção 6.
       ==================================================================== */
    if (action === "app_list") {
      const mapa = carregaApps();
      return { ok: true, data: {
        total: Object.keys(mapa).length,
        apps: Object.entries(mapa).map(([id, i]) => ({ id, aliases: i.aliases || [] })),
      } };
    }

    if (action === "app_scan") {
      const mapa = varreApps();
      return { ok: true, data: { total: Object.keys(mapa).length } };
    }

    if (action === "app_open" || action === "app_close") {
      const pedido = String(msg.args?.app || msg.args?.target || "");
      const fechando = action === "app_close";
      const app = resolveApp(pedido);
      const auditBase = { action_type: action, target: pedido, ts: Date.now() / 1000, ...provenance };

      if (!app) {
        const erro = `não conheço "${pedido}". Rode app_scan, ou use um dos apelidos de app_list.`;
        recordAudit({ entry: { ...auditBase, tier: 2, decision: "denied", result: `error:${erro}` },
                      sendToHub: sendAudit, filePath: auditFilePath });
        return { ok: false, data: { error: erro } };
      }

      const tier = (fechando || precisaConfirmar(app.id)) ? 2 : 1;
      let decisao = "auto";
      if (tier === 2) {
        const chave = `${action}:${app.id}`;
        decisao = alwaysCache.has(chave) ? "always" : null;
        if (!decisao) {
          const motivo = fechando
            ? "fechar um programa pode perder trabalho não salvo"
            : "abrir shell/editor de registro dá acesso amplo ao PC";
          decisao = await confirmFn({ command: `${fechando ? "FECHAR" : "ABRIR"} ${app.id}`,
                                      reason: motivo, tier: 2, tierLabel: "confirmar", provenance });
          if (decisao === "always") alwaysCache.add(chave);
        }
        if (decisao === "deny") {
          recordAudit({ entry: { ...auditBase, tier, decision: "deny", result: "error:negado no PC" },
                        sendToHub: sendAudit, filePath: auditFilePath });
          return { ok: false, data: { error: "você negou no PC" } };
        }
      }

      const r = fechando ? await fechaApp(app) : await abreApp(app);
      recordAudit({ entry: { ...auditBase, tier, decision: decisao,
                             result: r.ok ? "ok" : `error:${r.erro}` },
                    sendToHub: sendAudit, filePath: auditFilePath });
      return r.ok
        ? { ok: true, data: { app: app.id, jaEstavaFechado: r.jaEstavaFechado } }
        : { ok: false, data: { error: r.erro } };
    }

    if (action === "atalho_list") {
      const todos = carregaAtalhos();
      return { ok: true, data: {
        atalhos: Object.entries(todos).map(([nome, passos]) => ({ nome, passos: passos.length })),
      } };
    }

    if (action === "atalho_save") {
      return { ok: true, data: salvaAtalho(msg.args?.nome, msg.args?.passos) };
    }

    if (action === "atalho_delete") {
      return { ok: true, data: apagaAtalho(msg.args?.nome) };
    }

    /* `atalho_run` recebe um NOME, nunca os passos. Se aceitasse a lista, o
       atalho viraria um envelope: embrulhar qualquer ação nele atravessaria o
       gate com um pedido de cara inocente. Recebendo o nome, o pior que um
       backend comprometido consegue é disparar um atalho que o usuário JÁ
       escreveu no disco — o mesmo poder de apertar um botão que já existe.

       E cada passo volta pelo `handleCommand`, então continua sendo gateado um
       a um: fechar o Discord pergunta se fechar o Discord perguntaria. */
    if (action === "atalho_run") {
      const alvo = resolveAtalho(msg.args?.nome);
      if (!alvo) {
        return { ok: false, data: { error: `não existe atalho "${msg.args?.nome || ""}"` } };
      }
      const passos = [];
      for (const p of alvo.passos) {
        const sub = p.type === "url"
          ? { action: "open_url", args: { url: p.target }, ...provenance }
          : { action: p.action === "fechar" ? "app_close" : "app_open",
              args: { app: p.target }, ...provenance };
        const r = await handleCommand(sub);
        passos.push({ passo: `${p.type} ${p.action} ${p.target}`, ok: r.ok,
                      erro: r.ok ? undefined : r.data?.error });
      }
      /* Não para no primeiro erro: um app que não abriu não pode impedir os
         outros de fechar. O relatório diz o que foi e o que não foi — parar no
         meio deixaria o PC num estado que ninguém pediu. */
      const falhas = passos.filter((p) => !p.ok).length;
      return { ok: falhas === 0, data: { atalho: alvo.nome, passos, falhas } };
    }

    if (FS_ACTIONS.has(action)) {
      const op = action.slice(3); // "read" | "list" | "write" | "mkdir" | "delete" | "organize"
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
  "listen_status", "listen_config_set", "listen_start", "listen_stop",
]);

/* Um único loop de escuta por processo. Dois loops brigariam pelo microfone e
   dobrariam o custo de CPU sem escutar nada a mais. O callback de wake word é
   injetado pelo ws-client (é ele que sabe falar com o hub). */
let escuta = null;
let aoAcordar = null;

/** Chamado no boot pelo ws-client: define o que fazer quando a wake word bate. */
export function setWakeHandler(fn) { aoAcordar = fn; }

function garanteEscuta() {
  if (escuta) return escuta;
  escuta = createListener({
    onWake: (ev) => { try { aoAcordar?.(ev); } catch {} },
    onError: (motivo, dica) => console.warn("[escuta]", motivo, dica || ""),
  });
  return escuta;
}

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
        /* Dois modos, e o segundo é o que faz o JARVIS ouvir no aplicativo de
           desktop: lá a página vem de file:// e o reconhecimento de fala do
           navegador não existe (depende de um serviço do Google que o Electron
           não embarca). Então o painel GRAVA o áudio e manda os bytes pra cá,
           onde o whisper roda de verdade.

           O arquivo temporário existe porque o whisper.cpp lê de disco, não de
           stdin. Ele é apagado no `finally` — inclusive quando a transcrição
           falha, senão áudio da pessoa se acumularia em %TEMP% pra sempre. */
        let alvo = args.path;
        let temporario = null;
        if (!alvo && args.audio_base64) {
          const bytes = Buffer.from(args.audio_base64, "base64");
          if (bytes.length > 25 * 1024 * 1024) {
            return { ok: false, data: { reason: "áudio maior que 25 MB" } };
          }
          const ext = (args.format || "webm").replace(/[^a-z0-9]/gi, "").slice(0, 5) || "webm";
          temporario = path.join(os.tmpdir(), `vtz-fala-${Date.now()}.${ext}`);
          await fsp.writeFile(temporario, bytes);
          alvo = temporario;
        }
        try {
          const r = await transcribe(alvo, args.overrides || {});
          if (!r.ok) return { ok: false, data: r };
          return { ok: true, data: { text: r.text, model: r.model,
                                     wake: detectWakeWord(r.text) } };
        } finally {
          if (temporario) await fsp.rm(temporario, { force: true }).catch(() => {});
        }
      }
      /* Escuta contínua ("Ei, JARVIS" sem clicar em nada). O status carrega o
         custo estimado junto — ligar isto é ASR rodando sem parar, e quem
         liga precisa ver a conta antes. */
      case "listen_status":
        return { ok: true, data: {
          ...garanteEscuta().status(),
          config: loadListenerConfig(),
          limites: LISTENER_LIMITES,
          gravadores: Object.keys(RECORDERS),
        } };
      case "listen_config_set":
        return { ok: true, data: { config: saveListenerConfig(args), setup: checkListener() } };
      case "listen_start": {
        const r = garanteEscuta().start();
        return r.ok ? { ok: true, data: r } : { ok: false, data: r };
      }
      case "listen_stop":
        return { ok: true, data: await garanteEscuta().stop() };

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
