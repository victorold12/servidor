/* O JARVIS estava LENDO a formatação em vez de falar o conteúdo: "asterisco
 * asterisco pronto", "hash hash título", emoji virando ruído, e URL soletrada
 * caractere a caractere. Um humano lendo o mesmo texto em voz alta não fala
 * nada disso — usa a formatação como pista de entonação e fala o conteúdo.
 *
 * Cada teste aqui é uma coisa que dava errado no ouvido do Victor.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { paraFala } from "../src/fala-natural.js";

/** Nada de marcador de markdown pode sobrar no que vai pro motor. */
const semMarcadores = (t) => !/[*_`#|~]|\[|\]/.test(t);

test("negrito, itálico e riscado somem, o texto fica", () => {
  const r = paraFala("**Pronto!** Instalei o *editor* e o ~~antigo~~ saiu.");
  assert.equal(r, "Pronto! Instalei o editor e o antigo saiu.");
  assert.ok(semMarcadores(r), r);
});

test("emoji não vira ruído", () => {
  const r = paraFala("Pronto! 🎉 Tudo certo ✅ e sem erro 🚀");
  assert.equal(r, "Pronto! Tudo certo e sem erro.");
  /* Nenhum resquício invisível: seletor de variação e juntador de largura zero
     sobram quando só se filtra o bloco principal, e alguns motores os leem. */
  assert.ok(!/[\u{1F000}-\u{1FAFF}\u{FE00}-\u{FE0F}\u{200D}]/u.test(r), JSON.stringify(r));
});

test("emoji composto (com tom de pele e juntador) some inteiro", () => {
  const r = paraFala("Família 👨‍👩‍👧 e joinha 👍🏽 aqui");
  assert.ok(!/[\u{1F000}-\u{1FAFF}\u{200D}\u{1F3FB}-\u{1F3FF}]/u.test(r), JSON.stringify(r));
  assert.match(r, /Família.*joinha aqui/);
});

test("título perde o hash e ganha pausa", () => {
  assert.equal(paraFala("## Resultado\nDeu certo"), "Resultado. Deu certo.");
});

test("lista vira frases curtas, não 'traço item'", () => {
  /* O ponto no fim de cada item é o que faz o motor respirar entre eles — sem
     isso a lista sai numa tirada só, ofegante. */
  assert.equal(paraFala("- abrir\n- fechar\n- salvar"), "abrir. fechar. salvar.");
  assert.equal(paraFala("1. primeiro\n2. segundo"), "primeiro. segundo.");
});

test("link fala o texto, não o endereço", () => {
  assert.equal(paraFala("Veja o [manual](https://exemplo.com/a?b=1) aqui"),
    "Veja o manual aqui.");
});

test("URL solta não é soletrada", () => {
  const r = paraFala("Baixe em https://github.com/victorold12/servidor/releases");
  assert.ok(!/https|github|com/i.test(r), r);
  assert.match(r, /link/);
});

test("caminho de arquivo fala só o nome", () => {
  /* "C dois pontos barra usuários barra VTz produti barra..." é o pior caso. */
  const r = paraFala("Salvei em C:\\Users\\VTz produti\\Documents\\prova-voz.wav");
  assert.match(r, /prova-voz\.wav/);
  assert.ok(!/Users|Documents|\\/.test(r), r);
});

test("bloco de código não é lido", () => {
  const r = paraFala("Rode assim:\n```js\nconst x = {a: 1};\n```\nPronto");
  assert.ok(!/const|\{|\}/.test(r), r);
  assert.match(r, /Rode assim.*Pronto/);
});

test("código curto fala o conteúdo, sem as crases", () => {
  assert.equal(paraFala("Use o `npm test` agora"), "Use o npm test agora.");
});

test("símbolos com leitura em português são traduzidos", () => {
  assert.match(paraFala("Ficou 100% pronto"), /100 por cento/);
  assert.match(paraFala("Custa R$ 50 por mês"), /50 reais/);
  assert.match(paraFala("Vai de A -> B"), /A para B/);
});

test("tabela vira pausa, não barra vertical", () => {
  const r = paraFala("| nome | valor |\n|---|---|\n| torch | 2.6.0 |");
  assert.ok(!r.includes("|"), r);
  assert.match(r, /nome, valor/);
});

test("pontuação repetida não vira gagueira", () => {
  assert.equal(paraFala("Espera... pronto!!!"), "Espera. pronto!");
  assert.equal(paraFala("Isso — aquilo"), "Isso, aquilo.");
});

test("sempre termina com pontuação", () => {
  /* Sem isso o motor corta a última sílaba: ele não sabe que a frase acabou. */
  assert.match(paraFala("sem ponto no fim"), /\.$/);
  assert.equal(paraFala("já tem?"), "já tem?");
});

test("texto vazio ou só formatação não vira frase", () => {
  assert.equal(paraFala(""), "");
  assert.equal(paraFala(null), "");
  assert.equal(paraFala("   \n\n  "), "");
  assert.equal(paraFala("```\ncodigo\n```"), "");
});

test("uma resposta de verdade sai limpa de ponta a ponta", () => {
  const bruto = [
    "## ✅ Pronto!",
    "",
    "Instalei **3 apps** (100% ok):",
    "- `chrome` — o navegador",
    "- `code` — o editor",
    "",
    "Detalhes em https://exemplo.com/x?y=1 🚀",
  ].join("\n");
  const r = paraFala(bruto);
  assert.ok(semMarcadores(r), r);
  assert.ok(!/https|🚀|✅/.test(r), r);
  assert.match(r, /Pronto/);
  assert.match(r, /100 por cento/);
  assert.match(r, /o navegador/);
});
