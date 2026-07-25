/**
 * Testa as ações de voz no dispatcher — o caminho que o backend usa.
 *
 * O ponto de atenção aqui é de segurança: ação de voz NÃO deve passar pelo gate
 * de tier (falar não toca arquivo do usuário), mas também não pode virar uma
 * porta pra escrever fora da pasta do agente nem pra empurrar arquivo enorme
 * pelo WebSocket. Estes testes fixam as duas coisas.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Diretório próprio: escrever config e amostra de voz aqui não toca no do usuário.
process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-disp-"));

const { createCommandHandler } = await import("../src/command-dispatcher.js");
const { voicesDir } = await import("../src/voice-config.js");

/** Handler com confirmação que EXPLODE: se for chamada, o teste falha. */
function handlerSemConfirmacao() {
  return createCommandHandler({
    getAllowedRoots: () => [os.tmpdir()],
    confirmFn: async () => { throw new Error("ação de voz não deveria pedir confirmação"); },
    sendAudit: () => {},
    auditFilePath: path.join(os.tmpdir(), `audit-voz-${Date.now()}.jsonl`),
  });
}

test("voice_status não pede confirmação e descreve o estado real", async () => {
  globalThis.fetch = async () => { throw new Error("ECONNREFUSED"); };
  const handle = handlerSemConfirmacao();
  const r = await handle({ type: "command", action: "voice_status", args: {} });

  assert.equal(r.ok, true);
  assert.equal(r.data.engines.chatterbox.up, false, "diz a verdade: não está rodando");
  assert.equal(r.data.engines.kokoro.up, false);
  assert.ok(r.data.ranges.exaggeration, "manda as faixas pra interface montar os sliders");
  assert.ok(Array.isArray(r.data.samples));
  assert.ok(r.data.stt.hint, "diz o que falta pro STT funcionar");
  assert.ok(r.data.engines_disponiveis.includes("navegador"));
});

test("voice_config_set prende valor fora da faixa (não vai cru pro motor)", async () => {
  const handle = handlerSemConfirmacao();
  const r = await handle({ type: "command", action: "voice_config_set",
    args: { engine: "kokoro", exaggeration: 99, speed: 3.5 } });

  assert.equal(r.ok, true);
  assert.equal(r.data.config.engine, "kokoro");
  assert.equal(r.data.config.exaggeration, 2.0, "grampeado no máximo");
  assert.equal(r.data.config.speed, 2.0);

  const volta = await handle({ type: "command", action: "voice_config_get", args: {} });
  assert.equal(volta.data.config.engine, "kokoro", "a escolha persiste");
});

test("voice_save_sample grava dentro da pasta do agente e nome sujo é neutralizado", async () => {
  const handle = handlerSemConfirmacao();
  const conteudo = Buffer.from("RIFFfake-wav-bytes");
  const r = await handle({ type: "command", action: "voice_save_sample",
    args: { name: "../../escapar.wav", data_base64: conteudo.toString("base64") } });

  assert.equal(r.ok, true);
  assert.ok(!r.data.saved.name.includes(".."), `nome sanitizado: ${r.data.saved.name}`);
  const destino = path.join(voicesDir(), r.data.saved.name);
  assert.equal(fs.existsSync(destino), true, "ficou na pasta de vozes");
  assert.ok(path.resolve(destino).startsWith(path.resolve(voicesDir())),
    "e não escapou da pasta");

  const lista = await handle({ type: "command", action: "voice_list_samples", args: {} });
  assert.ok(lista.data.samples.some((s) => s.name === r.data.saved.name));

  const del = await handle({ type: "command", action: "voice_delete_sample",
    args: { name: r.data.saved.name } });
  assert.equal(del.data.deleted, true);
  assert.equal(fs.existsSync(destino), false, "apagou de verdade");
});

test("voice_save_sample recusa payload vazio e gigante", async () => {
  const handle = handlerSemConfirmacao();

  const vazio = await handle({ type: "command", action: "voice_save_sample",
    args: { name: "v.wav" } });
  assert.equal(vazio.ok, false);
  assert.match(vazio.data.error, /sem data_base64/);

  const gigante = Buffer.alloc(9 * 1024 * 1024, 1).toString("base64");
  const grande = await handle({ type: "command", action: "voice_save_sample",
    args: { name: "grande.wav", data_base64: gigante } });
  assert.equal(grande.ok, false);
  assert.match(grande.data.error, /grande demais/);
});

test("tts_speak devolve o áudio em base64 quando o motor responde", async () => {
  const bytes = new Uint8Array([82, 73, 70, 70, 9, 9]);
  globalThis.fetch = async (url) => {
    if (!String(url).includes("8004")) throw new Error("ECONNREFUSED");
    return { ok: true, status: 200, arrayBuffer: async () => bytes.buffer };
  };
  const handle = handlerSemConfirmacao();
  const r = await handle({ type: "command", action: "tts_speak",
    args: { text: "olá senhor", overrides: { engine: "chatterbox", voice: null } } });

  assert.equal(r.ok, true);
  assert.equal(r.data.engine, "chatterbox");
  assert.equal(Buffer.from(r.data.audio_base64, "base64").length, bytes.length);
  assert.equal(r.data.mime, "audio/wav");
});

test("tts_speak sem motor no ar devolve ok:false com dica, não trava", async () => {
  globalThis.fetch = async () => { throw new Error("ECONNREFUSED"); };
  const handle = handlerSemConfirmacao();
  const r = await handle({ type: "command", action: "tts_speak",
    args: { text: "teste", overrides: { engine: "chatterbox", voice: null } } });

  assert.equal(r.ok, false);
  assert.match(r.data.reason, /nenhum motor/i);
  assert.ok(r.data.hint);
});

test("stt_transcribe sem modelo devolve motivo legível", async () => {
  const handle = handlerSemConfirmacao();
  const r = await handle({ type: "command", action: "stt_transcribe",
    args: { path: "/nao/existe.wav" } });
  assert.equal(r.ok, false);
  assert.match(r.data.reason, /não encontrado/);
});

test("stt_config_set só aceita modelo conhecido", async () => {
  const handle = handlerSemConfirmacao();
  const bom = await handle({ type: "command", action: "stt_config_set",
    args: { model: "small", threads: 4 } });
  assert.equal(bom.data.config.model, "small");

  const ruim = await handle({ type: "command", action: "stt_config_set",
    args: { model: "gpt-4" } });
  assert.equal(ruim.data.config.model, "small", "modelo inválido não troca nada");
});

test("ação de voz desconhecida é recusada com nome no erro", async () => {
  const handle = handlerSemConfirmacao();
  const r = await handle({ type: "command", action: "voice_hackear", args: {} });
  assert.equal(r.ok, false);
  assert.match(r.data.error, /desconhecida/);
});
