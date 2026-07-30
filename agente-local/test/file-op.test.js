/**
 * Testes das ações de arquivo estruturadas (runFileOp) + do cache de sessão
 * "sempre permitir" (Tier 2). Usa uma root temporária de verdade — fs real,
 * sem mock, porque o ponto é justamente o sandbox de caminho funcionar.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { runFileOp, runCommand } from "../src/safe-exec.js";
import { TIER } from "../src/tier-validator.js";

function tmpRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-fileop-"));
}

test("fs_write dentro da root é Tier 1 (auto) e cria o arquivo de verdade", async () => {
  const root = tmpRoot();
  const target = path.join(root, "nota.txt");
  const r = await runFileOp({ op: "write", path: target, content: "olá jarvis", allowedRoots: [root] });
  assert.equal(r.ok, true);
  assert.equal(r.tier, TIER.WRITE);
  assert.equal(r.decision, "auto");
  assert.equal(fs.readFileSync(target, "utf8"), "olá jarvis");
});

test("fs_write cria diretórios-pai que faltam (dentro da root)", async () => {
  const root = tmpRoot();
  const target = path.join(root, "sub", "prof", "x.txt");
  const r = await runFileOp({ op: "write", path: target, content: "y", allowedRoots: [root] });
  assert.equal(r.ok, true);
  assert.equal(fs.existsSync(target), true);
});

test("fs_read devolve o conteúdo como stdout", async () => {
  const root = tmpRoot();
  const target = path.join(root, "leia.txt");
  fs.writeFileSync(target, "conteudo lido");
  const r = await runFileOp({ op: "read", path: target, allowedRoots: [root] });
  assert.equal(r.ok, true);
  assert.equal(r.tier, TIER.READ);
  assert.equal(r.stdout, "conteudo lido");
});

test("fs_list lista as entradas da pasta (com flag dir)", async () => {
  const root = tmpRoot();
  fs.writeFileSync(path.join(root, "a.txt"), "1");
  fs.mkdirSync(path.join(root, "pasta"));
  const r = await runFileOp({ op: "list", path: root, allowedRoots: [root] });
  assert.equal(r.ok, true);
  assert.equal(r.tier, TIER.READ);
  const items = JSON.parse(r.stdout);
  const names = items.map((i) => i.name).sort();
  assert.deepEqual(names, ["a.txt", "pasta"]);
  assert.equal(items.find((i) => i.name === "pasta").dir, true);
});

test("fs_delete de ARQUIVO é Tier 1 e apaga", async () => {
  const root = tmpRoot();
  const target = path.join(root, "some.txt");
  fs.writeFileSync(target, "x");
  const r = await runFileOp({ op: "delete", path: target, allowedRoots: [root] });
  assert.equal(r.ok, true);
  assert.equal(r.tier, TIER.WRITE);
  assert.equal(fs.existsSync(target), false);
});

test("fs_delete de PASTA sobe pra Tier 2 (pede confirmação) e só apaga se confirmar", async () => {
  const root = tmpRoot();
  const dir = path.join(root, "apagar-me");
  fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, "dentro.txt"), "x");

  // sem confirmFn: nega (fail-safe), pasta continua lá
  const denied = await runFileOp({ op: "delete", path: dir, allowedRoots: [root] });
  assert.equal(denied.ok, false);
  assert.equal(denied.tier, TIER.CONFIRM);
  assert.equal(fs.existsSync(dir), true);

  // confirmando: apaga recursivo
  const ok = await runFileOp({ op: "delete", path: dir, allowedRoots: [root], confirmFn: async () => "once" });
  assert.equal(ok.ok, true);
  assert.equal(fs.existsSync(dir), false);
});

test("caminho FORA das roots é Tier 2 mesmo pra leitura (sandbox)", async () => {
  const root = tmpRoot();
  const outside = path.join(os.tmpdir(), "jarvis-fora-" + Date.now() + ".txt");
  fs.writeFileSync(outside, "segredo fora");
  const r = await runFileOp({ op: "read", path: outside, allowedRoots: [root] });
  assert.equal(r.ok, false, "sem confirmFn, Tier 2 nega");
  assert.equal(r.tier, TIER.CONFIRM);
  fs.rmSync(outside, { force: true });
});

test("traversal com .. não escapa da root (canonicaliza antes de classificar)", async () => {
  const root = tmpRoot();
  const escape = path.join(root, "..", "..", "etc", "passwd");
  const r = await runFileOp({ op: "read", path: escape, allowedRoots: [root] });
  assert.equal(r.tier, TIER.CONFIRM, "…/../../etc/passwd cai fora das roots");
});

test("arquivo sensível dentro da root (.env) sobe pra Tier 2 mesmo em leitura", async () => {
  const root = tmpRoot();
  const target = path.join(root, ".env");
  fs.writeFileSync(target, "TOKEN=x");
  const r = await runFileOp({ op: "read", path: target, allowedRoots: [root] });
  assert.equal(r.tier, TIER.CONFIRM);
});

test("op desconhecida devolve erro sem tocar em disco", async () => {
  const root = tmpRoot();
  const r = await runFileOp({ op: "chmod", path: path.join(root, "x"), allowedRoots: [root] });
  assert.equal(r.ok, false);
  assert.match(r.error, /operação de arquivo desconhecida/);
});

test("fs_write recusa conteúdo grande demais", async () => {
  const root = tmpRoot();
  const big = "a".repeat(2_000_001);
  const r = await runFileOp({ op: "write", path: path.join(root, "big.txt"), content: big, allowedRoots: [root] });
  assert.equal(r.ok, false);
  assert.match(r.error, /grande demais/);
});

/* ---------- Cache de sessão "sempre permitir" (Tier 2) ---------- */

test("'always' num comando faz a MESMA ação não perguntar de novo na sessão", async () => {
  const alwaysCache = new Set();
  let asks = 0;
  const confirmFn = async () => { asks++; return "always"; };

  const r1 = await runCommand({ command: "whoami", confirmFn, alwaysCache });
  assert.equal(r1.decision, "confirmed-always");
  const r2 = await runCommand({ command: "whoami", confirmFn, alwaysCache });
  assert.equal(r2.decision, "confirmed-always-cache");
  assert.equal(asks, 1, "só perguntou uma vez");
});

test("cache é por AÇÃO EXATA: outro comando (mesmo programa) pergunta de novo", async () => {
  const alwaysCache = new Set();
  let asks = 0;
  const confirmFn = async () => { asks++; return "always"; };

  await runCommand({ command: "algum-bin --a", confirmFn, alwaysCache });
  await runCommand({ command: "algum-bin --b", confirmFn, alwaysCache }); // args diferentes
  assert.equal(asks, 2, "argumento diferente = ação diferente = pergunta de novo (fecha injeção de args)");
});

test("'once' NÃO entra no cache — pergunta de novo na próxima", async () => {
  const alwaysCache = new Set();
  let asks = 0;
  const confirmFn = async () => { asks++; return "once"; };

  await runCommand({ command: "whoami", confirmFn, alwaysCache });
  await runCommand({ command: "whoami", confirmFn, alwaysCache });
  assert.equal(asks, 2);
});

test("cache de arquivo é por caminho canônico exato", async () => {
  const root = tmpRoot();
  const outside1 = path.join(os.tmpdir(), "jc1-" + Date.now() + ".txt");
  const outside2 = path.join(os.tmpdir(), "jc2-" + Date.now() + ".txt");
  fs.writeFileSync(outside1, "a"); fs.writeFileSync(outside2, "b");
  const alwaysCache = new Set();
  let asks = 0;
  const confirmFn = async () => { asks++; return "always"; };

  await runFileOp({ op: "read", path: outside1, allowedRoots: [root], confirmFn, alwaysCache });
  await runFileOp({ op: "read", path: outside1, allowedRoots: [root], confirmFn, alwaysCache }); // mesmo arquivo -> cache
  await runFileOp({ op: "read", path: outside2, allowedRoots: [root], confirmFn, alwaysCache }); // outro arquivo -> pergunta
  assert.equal(asks, 2);
  fs.rmSync(outside1, { force: true }); fs.rmSync(outside2, { force: true });
});

test("cache NUNCA libera Tier 3: 'always' num comando bloqueado não abre exceção", async () => {
  const alwaysCache = new Set();
  let asked = false;
  const confirmFn = async () => { asked = true; return "always"; };
  // rm -rf / é Tier 3 (blocklist) — nem chega a perguntar, então nada entra no cache
  const r = await runCommand({ command: "rm -rf /", confirmFn, alwaysCache });
  assert.equal(r.ok, false);
  assert.equal(asked, false);
  assert.equal(alwaysCache.size, 0, "nada de Tier 3 entra no cache de 'sempre permitir'");
});
