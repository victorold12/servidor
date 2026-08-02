/* O registro de capacidades é lido por quem está tentando descobrir por que
 * algo não funciona. Ele falhar, mentir ou sumir com um item é pior que não
 * existir — muda o comportamento de quem confia nele.
 *
 * O que fica travado:
 *   - toda capacidade declara O QUE DESTRAVA e COMO RESOLVER (sem isso o
 *     diagnóstico vira uma lista de nomes técnicos que não ajuda ninguém)
 *   - uma verificação que ESTOURA não derruba as outras
 *   - o que falta aparece primeiro
 *   - opcional não conta como faltando
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-cap-"));

const { CAPACIDADES, verificaTudo, faltando } = await import("../src/capacidades.js");

test("toda capacidade diz o que destrava e como resolver", () => {
  for (const [id, c] of Object.entries(CAPACIDADES)) {
    assert.ok(c.destrava?.length > 5, `${id}: falta "destrava" legível`);
    assert.ok(c.resolver?.length > 5, `${id}: falta "resolver"`);
    assert.equal(typeof c.verifica, "function", `${id}: falta verifica()`);
    /* "ffmpeg" não diz nada a quem só quer usar; "escuta contínua" diz. */
    assert.ok(!c.destrava.toLowerCase().startsWith(id.toLowerCase()),
      `${id}: "destrava" repete o nome técnico em vez de explicar o benefício`);
  }
});

test("uma verificação que estoura não derruba as outras", async () => {
  const original = CAPACIDADES.cofre.verifica;
  CAPACIDADES.cofre.verifica = async () => { throw new Error("boom proposital"); };
  try {
    const linhas = await verificaTudo(["cofre", "ffmpeg"]);
    assert.equal(linhas.length, 2, "a lista tem que vir inteira");
    const cofre = linhas.find((l) => l.id === "cofre");
    assert.equal(cofre.ok, false);
    assert.match(cofre.motivo, /verificação falhou/,
      "tem que dizer que foi a CHECAGEM que quebrou, não a capacidade");
  } finally {
    CAPACIDADES.cofre.verifica = original;
  }
});

test("o que falta vem primeiro", async () => {
  const original = { ...CAPACIDADES.ffmpeg };
  CAPACIDADES.ffmpeg.verifica = async () => ({ ok: false, motivo: "de teste" });
  CAPACIDADES.cofre.verifica = async () => ({ ok: true });
  try {
    const linhas = await verificaTudo(["cofre", "ffmpeg"]);
    assert.equal(linhas[0].id, "ffmpeg", "quem falta é o que a pessoa veio ver");
    assert.equal(linhas[1].ok, true);
  } finally {
    CAPACIDADES.ffmpeg.verifica = original.verifica;
  }
});

test("opcional não conta como faltando", async () => {
  assert.equal(CAPACIDADES.kokoro.opcional, true,
    "o Kokoro é o reserva: sem ele o Chatterbox continua falando");
  const originais = Object.fromEntries(
    Object.entries(CAPACIDADES).map(([k, v]) => [k, v.verifica]));
  for (const c of Object.values(CAPACIDADES)) c.verifica = async () => ({ ok: false, motivo: "x" });
  try {
    const faltam = await faltando();
    assert.ok(!faltam.some((c) => c.id === "kokoro"), "opcional ausente não é falta");
    assert.ok(faltam.some((c) => c.id === "chatterbox"), "o principal ausente é falta");
  } finally {
    for (const [k, v] of Object.entries(originais)) CAPACIDADES[k].verifica = v;
  }
});
