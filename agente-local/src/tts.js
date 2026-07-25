/**
 * TTS local do JARVIS — Chatterbox principal, Kokoro fallback (Seção 14).
 *
 * Os dois rodam como servidor local e falam a API de fala da OpenAI
 * (`POST /v1/audio/speech`), então o cliente aqui é o mesmo para ambos: muda a
 * URL, o nome da voz e quais parâmetros de calibração fazem sentido.
 *
 *   Chatterbox: github.com/resemble-ai/chatterbox
 *               servidor: github.com/devnen/Chatterbox-TTS-Server
 *               clona voz a partir de uma amostra e aceita exaggeration/cfg_weight
 *   Kokoro:     github.com/hexgrad/kokoro
 *               vozes prontas, sem clonagem; aceita velocidade
 *
 * Regra de degradação: tenta o motor escolhido; se ele não estiver de pé, tenta
 * o outro; se nenhum estiver, devolve `{ ok: false, reason }` em vez de silêncio.
 * Quem chamou decide o que fazer — o painel, por exemplo, cai na voz do
 * navegador (Web Speech), que sempre existe.
 */
import { loadVoiceConfig, voiceSamplePath } from "./voice-config.js";

const TIMEOUT_MS = 45_000;

/** Motor -> como montar a requisição. Só isto difere entre eles. */
const ENGINES = {
  chatterbox: {
    url: (cfg) => `${cfg.chatterboxUrl}/v1/audio/speech`,
    body: (cfg, texto) => {
      const corpo = {
        model: "chatterbox",
        input: texto,
        response_format: "wav",
        exaggeration: cfg.exaggeration,
        cfg_weight: cfg.cfg_weight,
        temperature: cfg.temperature,
        language: cfg.language,
      };
      // voz clonada: o servidor recebe o nome do arquivo de referência
      if (cfg.voice) corpo.voice = cfg.voice;
      return corpo;
    },
    health: (cfg) => `${cfg.chatterboxUrl}/health`,
  },
  kokoro: {
    url: (cfg) => `${cfg.kokoroUrl}/v1/audio/speech`,
    body: (cfg, texto) => ({
      model: "kokoro",
      input: texto,
      voice: cfg.voice || "pf_dora",     // voz feminina PT do Kokoro
      response_format: "wav",
      speed: cfg.speed,
    }),
    health: (cfg) => `${cfg.kokoroUrl}/health`,
  },
};

async function comTimeout(promessa, ms = TIMEOUT_MS) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await promessa(ctrl.signal);
  } finally {
    clearTimeout(timer);
  }
}

/** O motor está de pé? Usado pela aba de config pra mostrar o estado real. */
export async function probe(engine, cfg = loadVoiceConfig()) {
  const spec = ENGINES[engine];
  if (!spec) return { engine, up: false, reason: "motor desconhecido" };
  try {
    const resp = await comTimeout(
      (signal) => fetch(spec.health(cfg), { signal }), 4000);
    return { engine, up: resp.ok, status: resp.status };
  } catch (err) {
    // servidor não instalado/desligado é o caso comum, não um bug
    return { engine, up: false, reason: err.name === "AbortError" ? "sem resposta" : "não está rodando" };
  }
}

export async function probeAll(cfg = loadVoiceConfig()) {
  const [chatterbox, kokoro] = await Promise.all([
    probe("chatterbox", cfg), probe("kokoro", cfg),
  ]);
  return { chatterbox, kokoro };
}

async function falarCom(engine, texto, cfg) {
  const spec = ENGINES[engine];
  const resp = await comTimeout((signal) => fetch(spec.url(cfg), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec.body(cfg, texto)),
    signal,
  }));
  if (!resp.ok) {
    const detalhe = (await resp.text().catch(() => "")).slice(0, 200);
    throw new Error(`${engine} respondeu ${resp.status}: ${detalhe}`);
  }
  const audio = Buffer.from(await resp.arrayBuffer());
  if (!audio.length) throw new Error(`${engine} devolveu áudio vazio`);
  return audio;
}

/**
 * Gera o áudio da fala. Devolve { ok, engine, audio, mime } ou
 * { ok:false, reason, tried } — nunca lança por motor ausente, porque "não tem
 * TTS instalado" é estado normal e o chamador precisa poder decidir.
 */
export async function speak(texto, overrides = {}) {
  const limpo = String(texto || "").trim();
  if (!limpo) return { ok: false, reason: "texto vazio" };

  const cfg = { ...loadVoiceConfig(), ...overrides };

  if (cfg.engine === "navegador") {
    // decisão do usuário: quem fala é o Web Speech no navegador, não o agente
    return { ok: false, reason: "motor definido como navegador", delegate: "browser" };
  }

  // avisa cedo se a voz escolhida sumiu do disco, em vez de deixar o
  // servidor de TTS falhar com uma mensagem obscura
  if (cfg.engine === "chatterbox" && cfg.voice && !voiceSamplePath(cfg.voice)) {
    return { ok: false, reason: `a amostra de voz "${cfg.voice}" não está mais no disco` };
  }

  // o escolhido primeiro; o outro como rede de segurança (Seção 14: Kokoro é
  // fallback automático)
  const ordem = cfg.engine === "kokoro"
    ? ["kokoro", "chatterbox"]
    : ["chatterbox", "kokoro"];

  const tentativas = [];
  for (const engine of ordem) {
    try {
      const audio = await falarCom(engine, limpo, cfg);
      return {
        ok: true,
        engine,
        fallback: engine !== cfg.engine,   // o painel mostra que não foi o preferido
        audio,
        mime: "audio/wav",
        bytes: audio.length,
      };
    } catch (err) {
      tentativas.push({ engine, erro: err.message });
    }
  }

  return {
    ok: false,
    reason: "nenhum motor de TTS local respondeu",
    tried: tentativas,
    hint: "suba o Chatterbox-TTS-Server ou o Kokoro, ou mude o motor pra 'navegador'",
  };
}
