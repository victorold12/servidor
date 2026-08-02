/**
 * Registro de capacidades — o que este PC consegue fazer, e o que falta pra
 * conseguir o resto.
 *
 * ---------------------------------------------------------------------------
 * A REGRA QUE DEFINE ESTE ARQUIVO
 *
 * Toda verificação aqui EXERCITA O CAMINHO. Nenhuma confere presença.
 *
 * A diferença não é sutil, é a origem de quase todo defeito caro deste projeto:
 *
 *   - `whisper-cli.exe` existia, o caminho no stt.json conferia, o instalador
 *     dizia "[ok] instalado" — e ele morria com 0xC0000135 porque tinha sido
 *     copiado pra longe das próprias DLLs. Conferir o arquivo dava verde.
 *   - O Chatterbox subia, atendia na porta 8004, e não falava: o modelo tinha
 *     falhado ao carregar. Conferir o socket dava verde.
 *   - O stt.json estava no disco com o conteúdo certo e o agente descartava
 *     inteiro por causa de um BOM. Conferir o arquivo dava verde.
 *
 * Em todos, "existe" e "funciona" divergiram, e foi o "existe" que mentiu. Por
 * isso cada capacidade abaixo roda a coisa: chama o binário, importa o módulo,
 * lê a config pelo mesmo carregador que o app usa.
 *
 * ---------------------------------------------------------------------------
 * PARA QUE SERVE
 *
 * Um lugar só que responde "o que dá pra fazer agora". Consumido por:
 *   - `scripts/doctor.js`, que imprime o estado de tudo num comando;
 *   - o painel, que pode dizer "escuta indisponível: falta ffmpeg" ANTES de
 *     você tentar, com o comando pra resolver.
 *
 * Cada capacidade declara O QUE DESTRAVA, não o que ela é. "ffmpeg" não diz
 * nada a quem só quer usar; "escuta contínua (Ei, JARVIS)" diz.
 */
import { execFile } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

import { loadConfig as loadListener } from "./listener.js";
import { loadSttConfig, modelPath } from "./stt.js";
import { loadVoiceConfig } from "./voice-config.js";

/** Roda um executável só pra ver se ele roda. Não interpreta a saída. */
function rodou(bin, args, timeout = 6000) {
  return new Promise((resolve) => {
    execFile(bin, args, { shell: false, timeout, windowsHide: true }, (err) => {
      if (!err) return resolve({ ok: true });
      /* Código de saída != 0 ainda é "roda" — vários binários saem 1 no
         --version. O que reprova é não conseguir EXECUTAR: ENOENT (não existe)
         e as falhas de carregamento de biblioteca. */
      const cod = err.code;
      if (cod === "ENOENT") return resolve({ ok: false, motivo: "não encontrado" });
      if (typeof cod === "number" && cod !== 0 && !err.killed) {
        return resolve({ ok: true });
      }
      resolve({ ok: false, motivo: String(err.message).slice(0, 120) });
    });
  });
}

function portaAtende(porta, timeout = 800) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    const fim = (r) => { s.destroy(); resolve(r); };
    s.setTimeout(timeout);
    s.once("connect", () => fim(true));
    s.once("timeout", () => fim(false));
    s.once("error", () => fim(false));
    s.connect(porta, "127.0.0.1");
  });
}

/** O motor de voz responde E consegue sintetizar? Porta aberta não basta. */
async function motorDeVozPronto(base) {
  if (!(await portaAtende(new URL(base).port))) {
    return { ok: false, motivo: "não está rodando" };
  }
  try {
    const r = await fetch(`${base}/v1/audio/voices`, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return { ok: false, motivo: `respondeu ${r.status} ao listar vozes` };
    const n = (await r.json())?.voices?.length || 0;
    return n > 0
      ? { ok: true, detalhe: `${n} vozes disponíveis` }
      : { ok: false, motivo: "no ar, mas sem nenhuma voz instalada" };
  } catch (e) {
    return { ok: false, motivo: `no ar, mas não respondeu: ${String(e.message).slice(0, 60)}` };
  }
}

export const CAPACIDADES = {
  ffmpeg: {
    destrava: "escuta contínua (Ei, JARVIS) e ditado",
    resolver: "rode o instalador de vozes de novo — ele baixa o ffmpeg sem precisar de winget",
    async verifica() {
      const cfg = loadListener();
      const bin = cfg.ffmpegPath || "ffmpeg";
      const r = await rodou(bin, ["-hide_banner", "-version"]);
      return r.ok
        ? { ok: true, detalhe: cfg.ffmpegPath ? "caminho configurado" : "no PATH" }
        : { ok: false, motivo: r.motivo };
    },
  },

  whisper: {
    destrava: "transcrever o que você fala",
    resolver: "rode o instalador de vozes — ele baixa o programa e o modelo",
    async verifica() {
      const cfg = loadSttConfig();
      const modelo = modelPath(cfg);
      if (!fs.existsSync(modelo)) {
        return { ok: false, motivo: `modelo ${cfg.model} não está em ${cfg.modelsDir}` };
      }
      /* Roda o binário de verdade. Conferir só o arquivo foi exatamente o que
         deixou passar o whisper-cli separado das DLLs dele. */
      const r = await rodou(cfg.binary, ["--help"], 10000);
      return r.ok
        ? { ok: true, detalhe: `modelo ${cfg.model}` }
        : { ok: false, motivo: `o binário não executa (${r.motivo}). Falta DLL ao lado dele?` };
    },
  },

  chatterbox: {
    destrava: "voz clonada (o JARVIS falando)",
    resolver: "Configurações > Voz > Instalar TUDO neste PC; depois ligue as vozes",
    async verifica() {
      return motorDeVozPronto(loadVoiceConfig().chatterboxUrl);
    },
  },

  kokoro: {
    destrava: "voz reserva, se o Chatterbox cair",
    opcional: true,
    resolver: "precisa das Build Tools do Visual Studio (uma dependência dele compila do zero)",
    async verifica() {
      return motorDeVozPronto(loadVoiceConfig().kokoroUrl);
    },
  },

  cofre: {
    destrava: "guardar o token do backend no cofre do sistema",
    resolver: "reinstale o app — o cofre vem com ele (keytar)",
    async verifica() {
      try {
        const { getToken } = await import("./token-vault.js");
        await getToken();
        return { ok: true };
      } catch (e) {
        return { ok: false, motivo: String(e.message).slice(0, 120) };
      }
    },
  },

  backend: {
    destrava: "tudo que passa pela nuvem: conversa, documentos, agentes",
    resolver: "bandeja > Parear de novo…",
    async verifica() {
      const { loadConfig } = await import("./config.js");
      const cfg = loadConfig();
      if (!cfg?.backendUrl) return { ok: false, motivo: "este PC não está pareado" };
      try {
        const r = await fetch(`${cfg.backendUrl}/api/health`, { signal: AbortSignal.timeout(8000) });
        return r.ok
          ? { ok: true, detalhe: cfg.backendUrl }
          : { ok: false, motivo: `respondeu ${r.status}` };
      } catch (e) {
        /* O Render hiberna no plano grátis: a primeira chamada depois de um
           tempo parado demora e pode estourar. Isso NÃO é o mesmo que estar
           fora do ar, e dizer "fora do ar" mandaria caçar o problema errado. */
        return { ok: false, motivo: `sem resposta (${String(e.message).slice(0, 60)}) — pode estar hibernando` };
      }
    },
  },
};

/**
 * Verifica tudo em paralelo. Devolve lista ordenada: o que falta primeiro,
 * porque é o que a pessoa veio ver.
 */
export async function verificaTudo(ids = Object.keys(CAPACIDADES)) {
  const linhas = await Promise.all(ids.map(async (id) => {
    const c = CAPACIDADES[id];
    let r;
    try {
      r = await c.verifica();
    } catch (e) {
      /* Uma verificação que estoura não pode derrubar o diagnóstico inteiro —
         é justamente quando ele mais serve. */
      r = { ok: false, motivo: `a própria verificação falhou: ${String(e.message).slice(0, 80)}` };
    }
    return { id, destrava: c.destrava, opcional: !!c.opcional, resolver: c.resolver, ...r };
  }));
  return linhas.sort((a, b) => Number(a.ok) - Number(b.ok));
}

/** Só o que falta, pro painel avisar antes de a pessoa tentar. */
export async function faltando() {
  return (await verificaTudo()).filter((c) => !c.ok && !c.opcional);
}
