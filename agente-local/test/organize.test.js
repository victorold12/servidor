/**
 * "Organizar pasta" mexe em MUITOS arquivos de uma vez, a pedido de um modelo.
 * É a ação com maior potencial de estrago silencioso do agente: se ela apagar,
 * sobrescrever ou descer em subpasta, o usuário só descobre quando for procurar
 * um arquivo que não está mais lá.
 *
 * As três regras travadas aqui:
 *   1. Só o primeiro nível — "organizar Downloads" não varre o projeto lá dentro
 *   2. Nada é apagado nem sobrescrito — colisão vira "arquivo (2).pdf"
 *   3. Extensão desconhecida fica onde está
 * Mais: fora das roots, nem começa.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { runFileOp } from "../src/safe-exec.js";

const semPergunta = async () => "once";

function pastaComArquivos(arquivos) {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), "vtz-org-"));
  for (const [nome, conteudo] of Object.entries(arquivos)) {
    const alvo = path.join(raiz, nome);
    fs.mkdirSync(path.dirname(alvo), { recursive: true });
    fs.writeFileSync(alvo, conteudo ?? "x");
  }
  return raiz;
}

const organiza = (raiz) =>
  runFileOp({ op: "organize", path: raiz, allowedRoots: [raiz], confirmFn: semPergunta });

test("separa por tipo e relata o que fez", async () => {
  const raiz = pastaComArquivos({
    "contrato.pdf": null, "planilha.xlsx": null, "foto.jpg": null,
    "musica.mp3": null, "clipe.mp4": null, "instalador.exe": null,
    "script.py": null, "pacote.zip": null, "slides.pptx": null,
  });
  const r = await organiza(raiz);
  assert.equal(r.ok, true, r.error);
  const rel = JSON.parse(r.stdout);

  assert.equal(rel.total, 9);
  assert.ok(fs.existsSync(path.join(raiz, "Documentos", "contrato.pdf")));
  assert.ok(fs.existsSync(path.join(raiz, "Planilhas", "planilha.xlsx")));
  assert.ok(fs.existsSync(path.join(raiz, "Imagens", "foto.jpg")));
  assert.ok(fs.existsSync(path.join(raiz, "Audio", "musica.mp3")));
  assert.ok(fs.existsSync(path.join(raiz, "Videos", "clipe.mp4")));
  assert.ok(fs.existsSync(path.join(raiz, "Programas", "instalador.exe")));
  assert.ok(fs.existsSync(path.join(raiz, "Codigo", "script.py")));
  assert.ok(fs.existsSync(path.join(raiz, "Compactados", "pacote.zip")));
  assert.ok(fs.existsSync(path.join(raiz, "Slides", "slides.pptx")));
  assert.ok(rel.resumo.includes("Documentos"), rel.resumo);
});

test("regra 1: não desce em subpasta", async () => {
  const raiz = pastaComArquivos({
    "solto.pdf": null,
    "meu-projeto/codigo.py": null,
    "meu-projeto/leia.md": null,
  });
  const r = await organiza(raiz);
  assert.equal(r.ok, true, r.error);

  assert.ok(fs.existsSync(path.join(raiz, "Documentos", "solto.pdf")));
  // o projeto continua intacto, no lugar
  assert.ok(fs.existsSync(path.join(raiz, "meu-projeto", "codigo.py")),
    "entrou na subpasta — organizar Downloads não pode remexer um projeto lá dentro");
  assert.ok(fs.existsSync(path.join(raiz, "meu-projeto", "leia.md")));
  assert.equal(JSON.parse(r.stdout).total, 1);
});

test("regra 2: colisão de nome não sobrescreve", async () => {
  const raiz = pastaComArquivos({ "nota.pdf": "primeiro", "Documentos/nota.pdf": "ja-estava-la" });
  const r = await organiza(raiz);
  assert.equal(r.ok, true, r.error);

  assert.equal(fs.readFileSync(path.join(raiz, "Documentos", "nota.pdf"), "utf8"), "ja-estava-la",
    "sobrescreveu o arquivo que já estava lá");
  assert.equal(fs.readFileSync(path.join(raiz, "Documentos", "nota (2).pdf"), "utf8"), "primeiro");
});

test("regra 3: extensão desconhecida fica onde está", async () => {
  const raiz = pastaComArquivos({ "coisa.qualquercoisa": null, "sem-extensao": null, "certo.pdf": null });
  const r = await organiza(raiz);
  const rel = JSON.parse(r.stdout);

  assert.ok(fs.existsSync(path.join(raiz, "coisa.qualquercoisa")), "moveu extensão desconhecida");
  assert.ok(fs.existsSync(path.join(raiz, "sem-extensao")), "moveu arquivo sem extensão");
  assert.ok(rel.ignorados.includes("coisa.qualquercoisa"), rel.ignorados);
  assert.ok(rel.ignorados.includes("sem-extensao"), rel.ignorados);
  assert.equal(rel.total, 1);
});

test("nada é apagado: a soma de arquivos é a mesma no fim", async () => {
  const raiz = pastaComArquivos({
    "a.pdf": null, "b.jpg": null, "c.mp3": null, "d.desconhecido": null, "e.zip": null,
  });
  const contaTudo = (dir) => fs.readdirSync(dir, { withFileTypes: true })
    .reduce((n, e) => n + (e.isDirectory() ? contaTudo(path.join(dir, e.name)) : 1), 0);

  const antes = contaTudo(raiz);
  await organiza(raiz);
  assert.equal(contaTudo(raiz), antes, "sumiu arquivo entre o antes e o depois");
});

test("fora das roots nem começa", async () => {
  const raiz = pastaComArquivos({ "x.pdf": null });
  const outraRoot = fs.mkdtempSync(path.join(os.tmpdir(), "vtz-outra-"));
  let perguntou = false;
  const r = await runFileOp({
    op: "organize", path: raiz, allowedRoots: [outraRoot],
    confirmFn: async () => { perguntou = true; return "deny"; },
  });
  assert.equal(r.ok, false);
  assert.ok(perguntou, "deveria ter subido pra confirmação local");
  assert.ok(fs.existsSync(path.join(raiz, "x.pdf")), "mexeu mesmo sem permissão");
});

test("pasta vazia não é erro", async () => {
  const raiz = pastaComArquivos({});
  const r = await organiza(raiz);
  assert.equal(r.ok, true, r.error);
  assert.equal(JSON.parse(r.stdout).total, 0);
  assert.match(JSON.parse(r.stdout).resumo, /nada pra mover/);
});

test("apontar pra um arquivo em vez de pasta dá erro honesto", async () => {
  const raiz = pastaComArquivos({ "a.pdf": null });
  const r = await runFileOp({ op: "organize", path: path.join(raiz, "a.pdf"),
                              allowedRoots: [raiz], confirmFn: semPergunta });
  assert.equal(r.ok, false);
  assert.match(r.error, /não é uma pasta/);
});

test("rodar duas vezes é seguro (as pastas de categoria são ignoradas)", async () => {
  const raiz = pastaComArquivos({ "a.pdf": null, "b.jpg": null });
  await organiza(raiz);
  const r2 = await organiza(raiz);
  assert.equal(r2.ok, true, r2.error);
  assert.equal(JSON.parse(r2.stdout).total, 0, "moveu de novo o que já estava arrumado");
  assert.ok(fs.existsSync(path.join(raiz, "Documentos", "a.pdf")));
  assert.ok(!fs.existsSync(path.join(raiz, "Documentos", "Documentos")),
    "criou pasta dentro de pasta de categoria");
});
