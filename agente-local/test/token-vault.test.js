/**
 * A propriedade de segurança que mais importa aqui: quando o cofre do SO não
 * está disponível, as funções falham ALTO e CLARO, e — o ponto central — NÃO
 * criam nenhum arquivo texto como alternativa.
 *
 * Isso precisa ser verificável em QUALQUER plataforma, não só numa que por
 * acaso não tem keytar buildável (este sandbox de dev é Linux sem libsecret;
 * mas rodar a mesma suíte no CI do Windows, onde o keytar funciona de
 * verdade, quebrava essas asserções — não porque havia bug, mas porque elas
 * dependiam do ambiente "coincidentemente" falhar). Por isso os testes
 * injetam um loader que falha de propósito via _setImportForTest, em vez de
 * confiar que o keytar real vai estar quebrado.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { saveToken, getToken, deleteToken, _setImportForTest } from "../src/token-vault.js";

function forceKeytarFailure(t) {
  _setImportForTest(() => Promise.reject(new Error("simulado pro teste: keytar indisponível")));
  t.after(() => _setImportForTest(null));
}

test("saveToken sem keytar disponível: rejeita com mensagem clara (não lança genérico)", async (t) => {
  forceKeytarFailure(t);
  await assert.rejects(saveToken("um-token-secreto-qualquer"), /cofre de credenciais/i);
});

test("getToken sem keytar disponível: rejeita, não devolve undefined silenciosamente", async (t) => {
  forceKeytarFailure(t);
  await assert.rejects(getToken(), /cofre de credenciais/i);
});

test("deleteToken sem keytar disponível: rejeita", async (t) => {
  forceKeytarFailure(t);
  await assert.rejects(deleteToken(), /cofre de credenciais/i);
});

test("saveToken com token vazio rejeita ANTES de tentar o keytar", async (t) => {
  forceKeytarFailure(t);
  await assert.rejects(saveToken(""), /token vazio/);
  await assert.rejects(saveToken(undefined), /token vazio/);
});

test("propriedade de segurança central: nenhum arquivo texto-plano é criado como fallback", async (t) => {
  forceKeytarFailure(t);
  // Varre o home por qualquer arquivo nosso que pudesse conter o "segredo" —
  // a única gravação esperada em disco pra qualquer coisa relacionada a
  // token é ZERO, porque a função deve rejeitar antes de escrever qualquer coisa.
  const before = snapshotJarvisFiles();
  const secret = "token-que-NUNCA-pode-ir-pra-arquivo-" + Date.now();
  await assert.rejects(saveToken(secret));
  const after = snapshotJarvisFiles();
  assert.deepEqual(after, before, "nenhum arquivo novo apareceu em ~/.jarvis-agente");
  for (const file of after) {
    assert.ok(!safeRead(file).includes(secret), `o segredo NÃO deveria aparecer em ${file}`);
  }
});

test("com o keytar funcionando de verdade, saveToken/getToken completam sem erro", async (t) => {
  const store = new Map();
  _setImportForTest(() =>
    Promise.resolve({
      default: {
        setPassword: async (service, account, token) => { store.set(`${service}:${account}`, token); },
        getPassword: async (service, account) => store.get(`${service}:${account}`) ?? null,
        deletePassword: async (service, account) => store.delete(`${service}:${account}`),
      },
    })
  );
  t.after(() => _setImportForTest(null));

  await saveToken("token-de-verdade-123");
  assert.equal(await getToken(), "token-de-verdade-123");
  await deleteToken();
  assert.equal(await getToken(), null);
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
