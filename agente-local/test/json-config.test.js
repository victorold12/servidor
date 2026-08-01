/* O BOM que apagava a configuração inteira, em silêncio dos dois lados.
 *
 * O instalador escreve `stt.json` e `listener.json` pelo PowerShell, e o
 * `Set-Content -Encoding UTF8` do PowerShell 5.1 (o que o Windows tem) grava
 * UTF-8 COM BOM. O `JSON.parse` estoura no BOM, e como todo carregador do
 * agente envolvia o parse num `catch` que devolve os padrões, o efeito era:
 *
 *     no disco:  modelsDir = C:\...\Documents\VTz LLM\whisper\modelos
 *     o app lia: modelsDir = C:\...\.jarvis-agente\whisper-models   (padrão)
 *
 * O instalador dizia "[ok] stt.json atualizado", o arquivo ESTAVA lá com o
 * conteúdo certo, e o agente procurava o modelo do whisper numa pasta que nunca
 * existiu. Medido nesta máquina depois de o instalador rodar com sucesso.
 *
 * Consertar só o instalador não bastaria: o Bloco de Notas também salva com BOM
 * se alguém abrir o arquivo pra editar à mão. Quem LÊ tem que tolerar.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-bom-"));
const AGENTE = process.env.JARVIS_AGENT_DIR;

const { leJsonConfig } = await import("../src/json-config.js");
const { loadSttConfig } = await import("../src/stt.js");
const { loadConfig: loadListen } = await import("../src/listener.js");

const escreve = (nome, texto) => fs.writeFileSync(path.join(AGENTE, nome), texto);
const BOM = "\uFEFF";

test("leJsonConfig aceita arquivo com BOM", () => {
  escreve("x.json", BOM + JSON.stringify({ a: 1 }));
  assert.deepEqual(leJsonConfig(path.join(AGENTE, "x.json")), { a: 1 });
});

test("leJsonConfig aceita arquivo sem BOM", () => {
  escreve("y.json", JSON.stringify({ a: 2 }));
  assert.deepEqual(leJsonConfig(path.join(AGENTE, "y.json")), { a: 2 });
});

test("arquivo ausente e arquivo inválido devolvem null, não exceção", () => {
  assert.equal(leJsonConfig(path.join(AGENTE, "nao-existe.json")), null);
  escreve("z.json", "{isto não é json");
  assert.equal(leJsonConfig(path.join(AGENTE, "z.json")), null);
});

/* O caso real: o instalador escreveu com BOM e o agente ignorou tudo. */
test("stt.json com BOM é lido, não descartado", () => {
  escreve("stt.json", BOM + JSON.stringify({
    modelsDir: "D:\\VTz LLM\\whisper\\modelos",
    binary: "D:\\VTz LLM\\whisper\\programa\\whisper-cli.exe",
    model: "small",
  }));
  const cfg = loadSttConfig();
  assert.equal(cfg.modelsDir, "D:\\VTz LLM\\whisper\\modelos",
    "caiu no padrão — o apontamento do instalador foi perdido");
  assert.equal(cfg.binary, "D:\\VTz LLM\\whisper\\programa\\whisper-cli.exe");
  assert.equal(cfg.model, "small");
  /* O merge com os padrões continua valendo pras chaves ausentes. */
  assert.ok(cfg.threads > 0, "as chaves não escritas ainda vêm do padrão");
});

test("listener.json com BOM é lido, não descartado", () => {
  escreve("listener.json", BOM + JSON.stringify({ ffmpegPath: "D:\\VTz LLM\\ffmpeg\\ffmpeg.exe" }));
  const cfg = loadListen();
  assert.equal(cfg.ffmpegPath, "D:\\VTz LLM\\ffmpeg\\ffmpeg.exe",
    "sem isto a escuta procura ffmpeg no PATH e não acha");
  assert.equal(cfg.chunkSec, 4, "as chaves não escritas ainda vêm do padrão");
});
