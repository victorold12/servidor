/**
 * Testa o loop de escuta contínua ("Ei, JARVIS" sem clicar em nada).
 *
 * O loop de verdade é exercitado com gravador e whisper FALSOS — dois scripts
 * de shell criados aqui, um que escreve um WAV e outro que imprime a
 * transcrição. Isso testa o que pode machucar de fato: o encadeamento
 * gravar → transcrever → detectar → callback, o apagamento do áudio depois de
 * transcrever, e o parar sem deixar processo pendurado. Um teste que só
 * chamasse as funções puras não pegaria nada disso.
 *
 * Foco:
 *   - config fora da faixa é presa no limite, não chega crua no gravador
 *   - sem gravador na máquina, a escuta se recusa a começar e diz o motivo
 *   - áudio do microfone NÃO fica em disco depois do ciclo
 *   - wake word dispara o callback com o comando separado da saudação
 *   - fala sem wake word não dispara nada
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-escuta-"));
const AGENTE = process.env.JARVIS_AGENT_DIR;

const listener = await import("../src/listener.js");
const {
  createListener, checkSetup, custo, defaults, detectRecorder, LIMITES,
  loadConfig, RECORDERS, saveConfig,
} = listener;

// ---------------------------------------------------------------- config
test("padrão é escuta desligada — microfone ligado é opt-in", () => {
  assert.equal(defaults().enabled, false);
  assert.equal(loadConfig().enabled, false);
});

test("chunkSec e pausaMs fora da faixa são presos no limite", () => {
  assert.equal(saveConfig({ chunkSec: 999 }).chunkSec, LIMITES.chunkSec.max);
  assert.equal(saveConfig({ chunkSec: 0 }).chunkSec, LIMITES.chunkSec.min);
  assert.equal(saveConfig({ pausaMs: -50 }).pausaMs, LIMITES.pausaMs.min);
  assert.equal(saveConfig({ pausaMs: 90_000 }).pausaMs, LIMITES.pausaMs.max);
});

test("campo vazio/nulo/booleano não vira 0 no lugar do valor atual", () => {
  const antes = saveConfig({ chunkSec: 6 }).chunkSec;
  assert.equal(antes, 6);
  assert.equal(saveConfig({ chunkSec: null }).chunkSec, 6);
  assert.equal(saveConfig({ chunkSec: "" }).chunkSec, 6);
  assert.equal(saveConfig({ chunkSec: true }).chunkSec, 6);
});

test("gravador desconhecido é ignorado em vez de gravado", () => {
  saveConfig({ recorder: "gravador-que-nao-existe" });
  assert.notEqual(loadConfig().recorder, "gravador-que-nao-existe");
  assert.equal(saveConfig({ recorder: "ffmpeg" }).recorder, "ffmpeg");
  assert.equal(saveConfig({ recorder: "auto" }).recorder, "auto");
});

test("device não cresce sem limite", () => {
  assert.ok(saveConfig({ device: "x".repeat(5000) }).device.length <= 200);
});

// ---------------------------------------------------------------- detecção
test("gravador ausente devolve motivo e dica, não exceção", () => {
  const r = detectRecorder("sox");   // "rec" não existe neste container
  if (r.ok) {
    assert.equal(r.recorder, "sox");            // se existir, ok — mas tem que nomear
  } else {
    assert.match(r.reason, /gravador/i);
    assert.ok(r.hint && r.hint.length > 10, "precisa dizer o que instalar");
    assert.ok(Array.isArray(r.tried) && r.tried.length, "precisa dizer o que tentou");
  }
});

test("checkSetup lista o que falta em vez de só dizer que não está pronto", () => {
  const s = checkSetup();
  assert.equal(typeof s.ready, "boolean");
  assert.ok(Array.isArray(s.missing));
  if (!s.ready) assert.ok(s.missing.length > 0);
});

test("o custo da escuta contínua é declarado, não escondido", () => {
  saveConfig({ chunkSec: 4 });
  const c = custo();
  assert.equal(c.transcricoes_por_hora, 900);       // 3600/4
  assert.match(c.aviso, /whisper/i);
  assert.match(c.aviso, /não é um detector de wake word/i);
});

test("escuta se recusa a começar sem gravador, dizendo por quê", () => {
  saveConfig({ recorder: "sox" });
  const l = createListener({});
  const r = l.start();
  if (!checkSetup().ready) {
    assert.equal(r.ok, false);
    assert.match(r.reason, /faltando/i);
    assert.equal(l.running, false);
  }
});

/* Os três testes do loop usam scripts POSIX (#!/bin/sh) como gravador e whisper
   falsos. No Windows isso não roda: spawn com shell:false não executa .cmd/.bat
   (bloqueado desde a correção do CVE-2024-27980 no Node), então não há como
   montar o mesmo falso lá. O que é específico do Windows — os argumentos do
   ffmpeg com -f dshow — está coberto pelo último teste, que roda em todo lugar.
   Fora do POSIX, estes três são declarados como pulados em vez de falharem. */
const SO_POSIX = os.platform() !== "win32";
const soPosix = { skip: SO_POSIX ? false : "loop com gravador falso só roda em POSIX" };

// ---------------------------------------------------------------- loop real
/* Gravador e whisper falsos: scripts de shell de verdade, chamados por spawn
   igual aos reais. É o que permite testar o encadeamento inteiro sem hardware. */
function montaFalsos(transcricao) {
  const bin = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-bin-"));

  // WAV PCM 16-bit mono 16 kHz mínimo, pra transcribe() achar o arquivo válido
  const gravador = path.join(bin, "arecord");
  fs.writeFileSync(gravador, `#!/bin/sh
# último argumento é o destino
for a in "$@"; do dest="$a"; done
printf 'RIFF$\\000\\000\\000WAVEfmt ' > "$dest"
dd if=/dev/zero bs=1 count=64 >> "$dest" 2>/dev/null
exit 0
`, { mode: 0o755 });

  const whisper = path.join(bin, "whisper-cli");
  fs.writeFileSync(whisper, `#!/bin/sh
[ "$1" = "--version" ] && echo "falso" && exit 0
echo "${transcricao}"
exit 0
`, { mode: 0o755 });

  // o modelo precisa existir em disco: transcribe() checa antes de rodar
  const modelos = path.join(AGENTE, "whisper-models");
  fs.mkdirSync(modelos, { recursive: true });
  fs.writeFileSync(path.join(modelos, "ggml-base.bin"), "modelo falso");

  process.env.PATH = `${bin}:${process.env.PATH}`;
  return { bin, modelos };
}

test("loop completo: grava, transcreve, detecta a wake word e separa o comando", soPosix, async () => {
  montaFalsos("Ei JARVIS abre o navegador");
  const { saveSttConfig } = await import("../src/stt.js");
  saveSttConfig({ binary: "whisper-cli", model: "base",
                  modelsDir: path.join(AGENTE, "whisper-models") });
  saveConfig({ recorder: "arecord", chunkSec: 2, pausaMs: 0 });

  const setup = checkSetup();
  assert.equal(setup.ready, true, `escuta deveria estar pronta: ${JSON.stringify(setup)}`);

  const acordou = [];
  const erros = [];
  const l = createListener({
    onWake: (ev) => acordou.push(ev),
    onError: (m) => erros.push(m),
  });

  const r = l.start();
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(r.recorder, "arecord");
  assert.ok(r.custo.transcricoes_por_hora > 0, "start declara o custo");

  // espera o primeiro match (o ciclo é rápido com os falsos)
  const limite = Date.now() + 15_000;
  while (!acordou.length && Date.now() < limite) {
    await new Promise((res) => setTimeout(res, 120));
  }
  await l.stop();

  assert.ok(acordou.length >= 1, `nenhum wake word detectado. erros: ${erros.join(" | ")}`);
  const ev = acordou[0];
  assert.equal(ev.greeted, true, '"Ei" antes do nome tem que ser reconhecido como saudação');
  assert.equal(ev.command, "abre o navegador", "o comando é o que vem depois do nome");
  assert.match(ev.transcript, /JARVIS/i);
  assert.equal(l.running, false, "stop tem que parar de verdade");
});

test("o áudio do microfone não fica em disco depois do ciclo", soPosix, async () => {
  montaFalsos("Ei JARVIS que horas são");
  const { saveSttConfig } = await import("../src/stt.js");
  saveSttConfig({ binary: "whisper-cli", model: "base",
                  modelsDir: path.join(AGENTE, "whisper-models") });
  saveConfig({ recorder: "arecord", chunkSec: 2, pausaMs: 0 });

  const l = createListener({ onWake: () => {} });
  assert.equal(l.start().ok, true);
  await new Promise((res) => setTimeout(res, 2500));
  await l.stop();

  const dir = path.join(AGENTE, "escuta");
  const sobrou = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith(".wav")) : [];
  assert.deepEqual(sobrou, [], `gravação do microfone sobrou em disco: ${sobrou.join(", ")}`);
});

test("fala sem a wake word não dispara nada", soPosix, async () => {
  montaFalsos("preciso comprar pão amanhã de manhã");
  const { saveSttConfig } = await import("../src/stt.js");
  saveSttConfig({ binary: "whisper-cli", model: "base",
                  modelsDir: path.join(AGENTE, "whisper-models") });
  saveConfig({ recorder: "arecord", chunkSec: 2, pausaMs: 0 });

  const acordou = [];
  const trechos = [];
  const l = createListener({ onWake: (e) => acordou.push(e), onChunk: (t) => trechos.push(t) });
  assert.equal(l.start().ok, true);
  const limite = Date.now() + 12_000;
  while (!trechos.length && Date.now() < limite) {
    await new Promise((res) => setTimeout(res, 120));
  }
  await l.stop();

  assert.ok(trechos.length >= 1, "o loop tem que ter transcrito algo");
  assert.equal(acordou.length, 0, "não pode acordar sem a wake word");
});

test("todo gravador conhecido monta argumentos em array, nunca string de shell", () => {
  for (const [nome, r] of Object.entries(RECORDERS)) {
    const args = r.args("/tmp/x.wav", { chunkSec: 4, device: "" });
    assert.ok(Array.isArray(args), `${nome} devolveu ${typeof args}`);
    for (const a of args) {
      assert.equal(typeof a, "string", `${nome} tem argumento não-string`);
      assert.ok(!/[|;&`$]/.test(a) || a.includes("audio="),
                `${nome} tem metacaractere de shell no argumento: ${a}`);
    }
    assert.ok(args.includes("/tmp/x.wav"), `${nome} não passa o destino`);
  }
});
