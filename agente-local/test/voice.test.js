/**
 * Testa a camada de voz: preferências, TTS (Chatterbox/Kokoro) e STT/wake word.
 *
 * Nada de servidor de TTS nem binário do whisper de verdade — este container não
 * tem nenhum dos dois. O `fetch` é substituído e o whisper é exercitado pelo
 * caminho de "binário ausente", que é justamente o estado em que o usuário
 * começa.
 *
 * O foco é o que pode machucar:
 *   - calibração fora da faixa não pode chegar crua no motor de TTS
 *   - nome de voz com ".." ou barra não pode ler arquivo fora da pasta
 *   - motor ausente tem que virar motivo legível, não exceção nem silêncio
 *   - fallback Chatterbox -> Kokoro precisa acontecer e ser declarado
 *   - wake word tem que tolerar o que a transcrição erra, sem disparar à toa
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Redireciona o diretório do agente ANTES de qualquer leitura: sem isto o teste
// leria (e sobrescreveria) a configuração de voz real em ~/.jarvis-agente.
process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-voz-"));

const { sanitize, DEFAULTS, RANGES, ENGINES } = await import("../src/voice-config.js");
const { speak, probe } = await import("../src/tts.js");
const { detectWakeWord, parseTranscript, transcribe, checkSetup, MODELS } = await import("../src/stt.js");

// ------------------------------------------------------------ calibração
test("sanitize prende a calibração na faixa em vez de passar valor cru", () => {
  const alto = sanitize({ exaggeration: 99, cfg_weight: -5, temperature: 1000 });
  assert.equal(alto.exaggeration, RANGES.exaggeration.max);
  assert.equal(alto.cfg_weight, RANGES.cfg_weight.min);
  assert.equal(alto.temperature, RANGES.temperature.max);

  const meio = sanitize({ exaggeration: 1.2 });
  assert.equal(meio.exaggeration, 1.2, "valor válido passa intacto");
});

test("sanitize ignora valor não numérico e mantém o que já valia", () => {
  const r = sanitize({ exaggeration: "muito", speed: null });
  assert.equal(r.exaggeration, DEFAULTS.exaggeration);
  assert.equal(r.speed, DEFAULTS.speed);
});

test("sanitize só aceita motor conhecido", () => {
  assert.equal(sanitize({ engine: "elevenlabs" }).engine, DEFAULTS.engine);
  for (const e of ENGINES) assert.equal(sanitize({ engine: e }).engine, e);
});

test("nome de voz é reduzido ao arquivo — sem escapar da pasta", () => {
  assert.equal(sanitize({ voice: "../../.ssh/id_rsa" }).voice, "id_rsa");
  assert.equal(sanitize({ voice: "/etc/passwd" }).voice, "passwd");
  assert.equal(sanitize({ voice: "minha-voz.wav" }).voice, "minha-voz.wav");
  assert.equal(sanitize({ voice: null }).voice, null);
});

test("sanitize só aceita URL http(s) pros servidores locais", () => {
  assert.equal(sanitize({ chatterboxUrl: "file:///etc" }).chatterboxUrl, DEFAULTS.chatterboxUrl);
  assert.equal(sanitize({ chatterboxUrl: "http://127.0.0.1:9000/" }).chatterboxUrl,
    "http://127.0.0.1:9000", "barra final é removida");
});

// ------------------------------------------------------------------- TTS
function fakeFetch(rotas) {
  globalThis.fetch = async (url, opts = {}) => {
    const chave = Object.keys(rotas).find((k) => String(url).includes(k));
    if (!chave) throw new Error("ECONNREFUSED");
    return rotas[chave](String(url), opts);
  };
}
const okAudio = () => ({
  ok: true, status: 200,
  arrayBuffer: async () => new Uint8Array([82, 73, 70, 70, 1, 2, 3, 4]).buffer,
});

test("speak usa o Chatterbox quando ele responde", async () => {
  let corpoVisto = null;
  fakeFetch({
    "8004/v1/audio/speech": (_u, o) => { corpoVisto = JSON.parse(o.body); return okAudio(); },
  });
  const r = await speak("olá senhor", { engine: "chatterbox", voice: null, exaggeration: 0.7 });
  assert.equal(r.ok, true);
  assert.equal(r.engine, "chatterbox");
  assert.equal(r.fallback, false);
  assert.equal(r.mime, "audio/wav");
  assert.ok(r.bytes > 0);
  /* Com ponto no fim: o `speak` passa o texto por `paraFala()` antes de mandar
     pro motor, e ela fecha a frase. Não é enfeite — sem pontuação final o
     motor não sabe que a frase acabou e corta a última sílaba. */
  assert.equal(corpoVisto.input, "olá senhor.");
  assert.equal(corpoVisto.exaggeration, 0.7, "manda a calibração pro motor");
});

/* Sem amostra clonada, o JARVIS não falava NADA pelo Chatterbox: o
   `/v1/audio/speech` do servidor declara `voice: str` sem valor padrão, e o
   corpo só levava o campo quando havia voz clonada — resultado, `422 Field
   required` pra todo mundo que nunca gravou a própria voz. Nenhum teste pegou
   porque nenhum chegava a pedir uma frase a um servidor de verdade. */
test("sem voz clonada, descobre uma voz pronta no servidor", async () => {
  let corpoVisto = null;
  fakeFetch({
    "/v1/audio/voices": () => ({
      ok: true, status: 200,
      json: async () => ({ status: "ok", voices: ["Abigail.wav", "Olivia.wav"] }),
    }),
    "8004/v1/audio/speech": (_u, o) => {
      corpoVisto = JSON.parse(o.body);
      if (!corpoVisto.voice) return { ok: false, status: 422, text: async () => "Field required" };
      return okAudio();
    },
  });
  const r = await speak("olá senhor", { engine: "chatterbox", voice: null });
  assert.equal(r.ok, true, "devia ter falado usando uma voz pronta");
  assert.equal(corpoVisto.voice, "Abigail.wav", "usa a primeira voz que o servidor lista");
});

/* Duas camadas, de propósito. A descoberta acima cobre o servidor renomear as
   vozes — coisa que o instalador provoca sozinho, porque roda `git pull` a cada
   execução. Esta cobre o contrário: servidor que não expõe a lista (versão
   antiga) tem que continuar falando pela constante embutida, em vez de emudecer
   por causa de uma comodidade que falhou. */
test("se a lista de vozes não existe, cai na voz padrão embutida", async () => {
  let corpoVisto = null;
  fakeFetch({
    "8004/v1/audio/speech": (_u, o) => { corpoVisto = JSON.parse(o.body); return okAudio(); },
  });
  const r = await speak("olá senhor", { engine: "chatterbox", voice: null });
  assert.equal(r.ok, true, "a falha ao listar vozes não pode impedir a fala");
  assert.ok(corpoVisto.voice, "tem que mandar ALGUMA voz: sem o campo o servidor devolve 422");
  assert.match(corpoVisto.voice, /\.wav$/, "e tem que ser um arquivo de voz");
});

test("Chatterbox fora do ar cai no Kokoro E declara que foi fallback", async () => {
  let usouKokoro = false;
  fakeFetch({
    "8880/v1/audio/speech": () => { usouKokoro = true; return okAudio(); },
  });
  const r = await speak("teste", { engine: "chatterbox", voice: null });
  assert.equal(r.ok, true);
  assert.equal(r.engine, "kokoro");
  assert.equal(r.fallback, true, "o painel precisa saber que não foi o preferido");
  assert.ok(usouKokoro);
});

test("nenhum motor de pé: motivo legível, não exceção", async () => {
  fakeFetch({});
  const r = await speak("teste", { engine: "chatterbox", voice: null });
  assert.equal(r.ok, false);
  assert.match(r.reason, /nenhum motor/i);
  assert.equal(r.tried.length, 2, "reporta as duas tentativas");
  assert.match(r.hint, /Chatterbox|Kokoro/);
});

test("motor 'navegador' delega em vez de tentar servidor local", async () => {
  let chamou = false;
  fakeFetch({ "audio/speech": () => { chamou = true; return okAudio(); } });
  const r = await speak("teste", { engine: "navegador" });
  assert.equal(r.ok, false);
  assert.equal(r.delegate, "browser");
  assert.equal(chamou, false, "não bate em servidor nenhum");
});

test("texto vazio não vira requisição", async () => {
  let chamou = false;
  fakeFetch({ "audio/speech": () => { chamou = true; return okAudio(); } });
  const r = await speak("   ");
  assert.equal(r.ok, false);
  assert.equal(chamou, false);
});

test("voz escolhida que não existe mais é avisada antes de chamar o motor", async () => {
  let chamou = false;
  fakeFetch({ "audio/speech": () => { chamou = true; return okAudio(); } });
  const r = await speak("teste", { engine: "chatterbox", voice: "voz-que-nao-existe.wav" });
  assert.equal(r.ok, false);
  assert.match(r.reason, /não está mais no disco/);
  assert.equal(chamou, false);
});

test("erro HTTP do motor não é tratado como sucesso", async () => {
  fakeFetch({
    "8004/v1/audio/speech": () => ({ ok: false, status: 500, text: async () => "boom" }),
  });
  const r = await speak("teste", { engine: "chatterbox", voice: null });
  assert.equal(r.ok, false, "500 no Chatterbox e Kokoro ausente = falha");
  assert.ok(r.tried.some((t) => /500/.test(t.erro)));
});

test("áudio vazio também é falha", async () => {
  fakeFetch({
    "8004/v1/audio/speech": () => ({
      ok: true, status: 200, arrayBuffer: async () => new Uint8Array([]).buffer }),
  });
  const r = await speak("teste", { engine: "chatterbox", voice: null });
  assert.equal(r.ok, false);
});

test("probe distingue 'não está rodando' de erro real", async () => {
  fakeFetch({});
  const r = await probe("chatterbox");
  assert.equal(r.up, false);
  assert.match(r.reason, /não está rodando|sem resposta/);

  const desconhecido = await probe("piper");
  assert.equal(desconhecido.up, false);
  assert.match(desconhecido.reason, /desconhecido/);
});

// ------------------------------------------------------------------- STT
test("parseTranscript limpa os marcadores de tempo do whisper", () => {
  const bruto = [
    "whisper_init_from_file: loading model",
    "[00:00:00.000 --> 00:00:03.200]   Abre o Chrome pra mim",
    "[00:00:03.200 --> 00:00:05.000]   e pesquisa por notebooks",
  ].join("\n");
  assert.equal(parseTranscript(bruto), "Abre o Chrome pra mim e pesquisa por notebooks");
});

test("checkSetup diz o que falta quando o modelo não está baixado", () => {
  const s = checkSetup({ ...{}, model: "base",
    modelsDir: path.join(os.tmpdir(), "nao-existe-" + Date.now()), binary: "whisper-cli",
    language: "pt", threads: 4 });
  assert.equal(s.model_present, false);
  assert.equal(s.ready, false);
  assert.match(s.hint, /ggml-base\.bin/);
});

test("transcribe sem arquivo e sem modelo devolve motivo, não exceção", async () => {
  const semArquivo = await transcribe("/nao/existe.wav");
  assert.equal(semArquivo.ok, false);
  assert.match(semArquivo.reason, /não encontrado/);

  const tmp = path.join(os.tmpdir(), `audio-${Date.now()}.wav`);
  fs.writeFileSync(tmp, Buffer.from([0]));
  const semModelo = await transcribe(tmp, {
    modelsDir: path.join(os.tmpdir(), "sem-modelos-" + Date.now()) });
  assert.equal(semModelo.ok, false);
  assert.match(semModelo.reason, /modelo do whisper não encontrado/);
  fs.unlinkSync(tmp);
});

test("o modelo padrão é base, não large (Seção 9 — RAM)", () => {
  assert.equal(checkSetup().model, "base");
  assert.ok(MODELS.includes("large-v3"), "large existe como opção, só não é o padrão");
});

// ------------------------------------------------------------- wake word
test("wake word pega as variações que a transcrição costuma produzir", () => {
  for (const frase of [
    "Ei JARVIS", "ei, jarvis", "Hey Jarvis!", "ok jarvis", "jarvis",
    "Ei Jarvez", "e jarvis",
  ]) {
    assert.equal(detectWakeWord(frase).hit, true, `deveria pegar: ${frase}`);
  }
});

test("wake word entende o nome soletrado", () => {
  const r = detectWakeWord("ei j a r v i s abre o chrome");
  assert.equal(r.hit, true);
  assert.match(r.command, /abre o chrome/);
});

test("wake word separa o comando do chamado", () => {
  const r = detectWakeWord("Ei JARVIS, monta a planilha de julho");
  assert.equal(r.hit, true);
  assert.equal(r.greeted, true);
  assert.equal(r.command, "monta a planilha de julho");
});

test("chamado sem comando não inventa comando", () => {
  const r = detectWakeWord("ei jarvis");
  assert.equal(r.hit, true);
  assert.equal(r.command, null);
});

test("wake word NÃO dispara em fala comum", () => {
  for (const frase of [
    "", "   ", "abre o chrome", "o filme do homem de ferro é bom",
    "preciso de um serviço novo", "ei, tudo bem?",
  ]) {
    assert.equal(detectWakeWord(frase).hit, false, `não deveria disparar: ${frase}`);
  }
});
