/* Memória de aprovações.
 *
 * O QUE ESTE TESTE PROTEGE
 *
 * A memória existe pra combater fadiga de aprovação — que é falha de segurança,
 * não incômodo: um gate que pergunta demais treina a pessoa a clicar sim sem
 * ler, e aí ele para de proteger no dia em que a pergunta era diferente.
 *
 * Mas uma memória mal feita é pior que perguntar sempre. Os três jeitos de
 * errar, todos travados abaixo:
 *
 *   - aprovar por SEMELHANÇA (rm arquivo.log libera rm arquivo.txt)
 *   - virar caminho pra SUBIR DE NÍVEL (Tier 3 aprovado uma vez, aberto sempre)
 *   - durar PARA SEMPRE, num contexto que já mudou
 *
 * E uma regra que atravessa tudo: erro de leitura NUNCA vira permissão.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-aprov-"));

const { chaveDa, consulta, listar, registra, revoga } = await import("../src/aprovacoes.js");

const LER = { programa: "type", argumentos: ["notas.txt"], escopo: "Documentos", tier: 1 };

test.beforeEach(() => revoga());

test("perguntar uma vez, não dez", () => {
  assert.equal(consulta(LER).aprovado, false, "sem aprovação, pergunta");
  registra(LER);
  const r = consulta(LER);
  assert.equal(r.aprovado, true);
  assert.match(r.motivo, /aprovado em/, "tem que dizer POR QUE não perguntou");
});

test("NÃO aprova por semelhança — a chave é exata", () => {
  registra(LER);
  assert.equal(consulta({ ...LER, argumentos: ["outro.txt"] }).aprovado, false,
    "outro argumento é outra ação");
  assert.equal(consulta({ ...LER, programa: "del" }).aprovado, false,
    "outro programa é outra ação");
  assert.equal(consulta({ ...LER, escopo: "Downloads" }).aprovado, false,
    "'pode ler nesta pasta' não é 'pode ler naquela'");
});

test("aprovação NÃO é caminho pra subir de nível", () => {
  const destrutivo = { programa: "del", argumentos: ["/s", "C:\\"], tier: 3 };
  assert.equal(registra(destrutivo), false, "Tier 3 não entra na memória");
  const r = consulta(destrutivo);
  assert.equal(r.aprovado, false);
  assert.match(r.motivo, /não sobe nível/);
});

test("o mesmo comando reclassificado pra tier maior volta a perguntar", () => {
  registra({ ...LER, tier: 1 });
  const r = consulta({ ...LER, tier: 2 });
  assert.equal(r.aprovado, false,
    "o que foi aprovado como escrita não autoriza o mesmo reclassificado como suspeito");
  assert.match(r.motivo, /tier 1.*tier 2|tier 1, pedido no 2/);
});

test("toda aprovação tem prazo", () => {
  const t0 = Date.now();
  registra(LER, { prazoMs: 1000, agora: t0 });
  assert.equal(consulta(LER, t0 + 500).aprovado, true, "dentro do prazo vale");
  assert.equal(consulta(LER, t0 + 1500).aprovado, false, "depois do prazo, não");
  assert.match(consulta(LER, t0 + 1500).motivo, /expirou/);
});

test("o teto de 24h não é negociável", () => {
  const t0 = Date.now();
  registra(LER, { prazoMs: 365 * 24 * 3600 * 1000, agora: t0 });
  const um_dia = 24 * 3600 * 1000;
  assert.equal(consulta(LER, t0 + um_dia - 1000).aprovado, true);
  assert.equal(consulta(LER, t0 + um_dia + 1000).aprovado, false,
    "um teto que quem chama pode ignorar não é teto");
});

test("prazo zero ou negativo não registra nada", () => {
  assert.equal(registra(LER, { prazoMs: 0 }), false);
  assert.equal(registra(LER, { prazoMs: -5 }), false);
  assert.equal(consulta(LER).aprovado, false);
});

test("dá pra revogar — uma ou todas", () => {
  const outra = { ...LER, argumentos: ["b.txt"] };
  registra(LER);
  registra(outra);
  assert.equal(revoga(LER), true);
  assert.equal(consulta(LER).aprovado, false, "revogada");
  assert.equal(consulta(outra).aprovado, true, "a outra continua");
  revoga();
  assert.equal(consulta(outra).aprovado, false, "revoga tudo");
});

test("revogar o que não existe não mente", () => {
  assert.equal(revoga({ programa: "nunca", argumentos: [] }), false);
});

test("listar mostra o que está valendo, legível", () => {
  registra({ ...LER, descricao: "ler notas.txt em Documentos" }, { prazoMs: 3600_000 });
  const l = listar();
  assert.equal(l.length, 1);
  assert.equal(l[0].descricao, "ler notas.txt em Documentos",
    "auditar não pode exigir decifrar hash");
  assert.match(l[0].expiraEm, /min$/);
});

test("expirada some da lista sozinha", () => {
  const t0 = Date.now();
  registra(LER, { prazoMs: 1000, agora: t0 });
  assert.equal(listar(t0 + 5000).length, 0);
});

test("arquivo corrompido NÃO vira permissão", () => {
  registra(LER);
  fs.writeFileSync(path.join(process.env.JARVIS_AGENT_DIR, "aprovacoes.json"),
    "{ isto não é json", "utf8");
  assert.equal(consulta(LER).aprovado, false,
    "erro de leitura falha FECHADO — o contrário seria conceder por acidente");
  assert.deepEqual(listar(), []);
});

test("BOM não derruba (o PowerShell grava assim)", () => {
  registra(LER);
  const alvo = path.join(process.env.JARVIS_AGENT_DIR, "aprovacoes.json");
  fs.writeFileSync(alvo, "\uFEFF" + fs.readFileSync(alvo, "utf8"), "utf8");
  assert.equal(consulta(LER).aprovado, true,
    "um BOM já fez JSON.parse descartar config inteira neste projeto");
});

test("a chave é estável e não colide", () => {
  assert.equal(chaveDa(LER), chaveDa({ ...LER }), "mesma ação, mesma chave");
  assert.notEqual(chaveDa(LER), chaveDa({ ...LER, argumentos: ["x"] }));
  assert.equal(chaveDa({ programa: "TYPE", argumentos: [] }),
    chaveDa({ programa: "type", argumentos: [] }),
    "maiúscula no programa é a mesma coisa no Windows");
});

test("registrar de novo renova em vez de duplicar", () => {
  const t0 = Date.now();
  registra(LER, { prazoMs: 1000, agora: t0 });
  registra(LER, { prazoMs: 60_000, agora: t0 });
  assert.equal(listar(t0).length, 1, "não duplica");
  assert.equal(consulta(LER, t0 + 5000).aprovado, true, "o prazo novo vale");
});
