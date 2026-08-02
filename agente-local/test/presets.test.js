/* Perfis de instalação.
 *
 * O QUE ESTE TESTE PROTEGE
 *
 * Que as camadas realmente se acumulem. Um perfil que promete incluir o
 * anterior e não inclui produz a pior falha deste projeto: a que aparece longe
 * da causa — o usuário instala "voz", o ffmpeg não vem junto, e a escuta falha
 * com um erro que não menciona ffmpeg em lugar nenhum.
 *
 * E que os nomes das capacidades sejam REAIS. Um typo aqui faria o perfil pedir
 * algo que ninguém verifica, e o diagnóstico diria "completo" sobre um PC que
 * não está.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { CAPACIDADES } from "../src/capacidades.js";
import {
  PADRAO, PERFIS, capacidadesDe, diagnostica, paraEscolha, perfilAtual,
} from "../src/presets.js";

/** Verificador falso: diz quais capacidades estão presentes. */
const fingir = (presentes) => async (ids) =>
  ids.map((id) => ({
    id, ok: presentes.includes(id),
    opcional: !!CAPACIDADES[id]?.opcional,
    resolver: `resolva o ${id}`,
  }));

test("toda capacidade citada num perfil EXISTE de verdade", () => {
  for (const [nome, p] of Object.entries(PERFIS)) {
    for (const c of p.capacidades) {
      assert.ok(CAPACIDADES[c],
        `perfil ${nome} pede "${c}", que não existe em capacidades.js — ` +
        "o diagnóstico diria 'completo' sobre um PC que não está");
    }
  }
});

test("as camadas se acumulam", () => {
  const texto = capacidadesDe("texto");
  const escuta = capacidadesDe("escuta");
  const voz = capacidadesDe("voz");
  const local = capacidadesDe("local");

  for (const c of texto) assert.ok(escuta.includes(c), `escuta perdeu ${c}`);
  for (const c of escuta) assert.ok(voz.includes(c), `voz perdeu ${c}`);
  for (const c of voz) assert.ok(local.includes(c), `local perdeu ${c}`);

  assert.ok(voz.includes("ffmpeg"),
    "quem instala voz precisa do ffmpeg — sem isso a escuta falha com um erro " +
    "que não menciona ffmpeg em lugar nenhum");
});

test("cada camada acrescenta algo", () => {
  assert.ok(capacidadesDe("escuta").length > capacidadesDe("texto").length);
  assert.ok(capacidadesDe("voz").length > capacidadesDe("escuta").length);
  assert.ok(capacidadesDe("local").length > capacidadesDe("voz").length);
});

test("nada é pedido duas vezes", () => {
  const l = capacidadesDe("local");
  assert.equal(new Set(l).size, l.length, l);
});

test("o básico vem antes do avançado", () => {
  const l = capacidadesDe("voz");
  assert.ok(l.indexOf("ffmpeg") < l.indexOf("chatterbox"),
    "a ordem é a ordem de instalação");
});

test("perfil desconhecido é erro, não silêncio", () => {
  assert.throws(() => capacidadesDe("inventado"), /desconhecido/);
});

test("o padrão é o menor", () => {
  assert.equal(PADRAO, "texto");
  assert.equal(capacidadesDe(PADRAO).length,
    Math.min(...Object.keys(PERFIS).map((p) => capacidadesDe(p).length)),
    "o padrão tem que ser o mais barato: quem quer voz escolhe, e escolhendo entende");
});

test("diagnóstico aponta o que falta e o que fazer PRIMEIRO", async () => {
  const d = await diagnostica("voz", fingir(["cofre", "backend"]));
  assert.equal(d.completo, false);
  assert.ok(d.faltando.length >= 2, d.faltando);
  assert.equal(d.faltando[0].id, "ffmpeg",
    "as camadas dependem umas das outras: mandar consertar a última é mandar " +
    "consertar o sintoma");
  assert.match(d.proximoPasso, /ffmpeg/);
});

test("PC completo é reconhecido como completo", async () => {
  const tudo = capacidadesDe("local");
  const d = await diagnostica("local", fingir(tudo));
  assert.equal(d.completo, true);
  assert.deepEqual(d.faltando, []);
  assert.equal(d.proximoPasso, "");
});

test("capacidade OPCIONAL ausente não reprova o perfil", async () => {
  // O kokoro é reserva do chatterbox; exigi-lo faria um PC saudável parecer
  // quebrado.
  const d = await diagnostica("voz", fingir(capacidadesDe("voz")));
  assert.equal(d.completo, true);
});

test("perfilAtual devolve o MAIOR que o PC atende", async () => {
  assert.equal(await perfilAtual(fingir(capacidadesDe("escuta"))), "escuta");
  assert.equal(await perfilAtual(fingir(capacidadesDe("local"))), "local");
  assert.equal(await perfilAtual(fingir(["cofre", "backend"])), "texto");
});

test("PC que não atende nem o mínimo devolve null, não 'texto'", async () => {
  assert.equal(await perfilAtual(fingir([])), null,
    "dizer 'texto' sobre um PC sem cofre nem backend seria a mentira cara");
});

test("a lista de escolha é legível por humano", () => {
  const lista = paraEscolha();
  assert.equal(lista.length, Object.keys(PERFIS).length);
  for (const p of lista) {
    assert.ok(p.titulo.length > 3, p);
    assert.ok(p.descricao.length > 20, `${p.id}: descrição curta demais`);
    assert.ok(p.tempo, `${p.id}: falta dizer quanto demora`);
    // Sem isso a pessoa escolhe "completo" sem saber que são dezenas de
    // minutos e vários GB, e descobre pelo relógio.
  }
  assert.equal(lista.filter((p) => p.padrao).length, 1, "um padrão, e só um");
});
