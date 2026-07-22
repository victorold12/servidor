/**
 * Este ambiente não tem keytar buildável (sem libsecret/D-Bus) — o que dá pra
 * testar de verdade AQUI é exatamente a propriedade de segurança que mais
 * importa: quando o cofre do SO não está disponível, as funções falham ALTO
 * e CLARO, e — o ponto central — NÃO criam nenhum arquivo texto como
 * alternativa. O caminho "keytar funcionando" só é verificável numa máquina
 * real (Windows/macOS/Linux com libsecret) — ver aviso no topo de src/token-vault.js.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { saveToken, getToken, deleteToken, _resetForTest } from "../src/token-vault.js";

test("saveToken sem keytar disponível: rejeita com mensagem clara (não lança genérico)", async () => {
  _resetForTest();
  await assert.rejects(saveToken("um-token-secreto-qualquer"), /cofre de credenciais/i);
});

test("getToken sem keytar disponível: rejeita, não devolve undefined silenciosamente", async () => {
  _resetForTest();
  await assert.rejects(getToken(), /cofre de credenciais/i);
});

test("deleteToken sem keytar disponível: rejeita", async () => {
  _resetForTest();
  await assert.rejects(deleteToken(), /cofre de credenciais/i);
});

test("saveToken com token vazio rejeita ANTES de tentar o keytar", async () => {
  _resetForTest();
  await assert.rejects(saveToken(""), /token vazio/);
  await assert.rejects(saveToken(undefined), /token vazio/);
});

test("propriedade de segurança central: nenhum arquivo texto-plano é criado como fallback", async () => {
  _resetForTest();
  // Varre o home (deste ambiente de teste) por qualquer arquivo nosso que
  // pudesse conter o "segredo" — a única gravação esperada em disco pra
  // qualquer coisa relacionada a token é ZERO, porque a função deve rejeitar
  // antes de escrever qualquer coisa.
  const before = snapshotJarvisFiles();
  const secret = "token-que-NUNCA-pode-ir-pra-arquivo-" + Date.now();
  await assert.rejects(saveToken(secret));
  const after = snapshotJarvisFiles();
  assert.deepEqual(after, before, "nenhum arquivo novo apareceu em ~/.jarvis-agente");
  for (const file of after) {
    assert.ok(!safeRead(file).includes(secret), `o segredo NÃO deveria aparecer em ${file}`);
  }
});

function safeRead(f) {
  try { return fs.readFileSync(f, "utf8"); } catch { return ""; }
}

function snapshotJarvisFiles() {
  const dir = path.join(os.homedir(), ".jarvis-agente");
  try {
    return fs.readdirSync(dir).map((f) => path.join(dir, f)).sort();
  } catch {
    return [];
  }
}
