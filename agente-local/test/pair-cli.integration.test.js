/**
 * Roda o pair-cli.js DE VERDADE (processo filho) contra o backend Python real,
 * confirmando pelo HTTP como o navegador faria. Prova a fiação completa:
 * prompt -> pairWithBackend -> mostra o código -> poll -> approved -> saveToken.
 *
 * O desfecho de saveToken() depende do cofre do SO estar disponível — varia
 * por ambiente:
 *   - Aqui (Linux sem libsecret/D-Bus): keytar não builda -> falha ALTA e
 *     CLARA (mensagem do token-vault), nunca crash silencioso.
 *   - CI Windows real (keytar com binário pré-compilado, Credential Manager
 *     disponível): pareamento deve completar de verdade.
 * O teste aceita os dois desfechos, mas cada um com a asserção certa — não é
 * "aceita qualquer coisa", é "aceita qualquer um dos dois comportamentos
 * corretos conhecidos", nunca um terceiro (crash, timeout, mensagem genérica).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { sobeBackend, fetchTeimoso } from "./_backend.js";

const SESSION_TOKEN = "test-session-token";
const AGENT_ROOT = path.resolve(import.meta.dirname, "..");

test("pair-cli.js: fluxo completo até o cofre do SO — sucesso real OU falha alta e clara, nunca crash", async (t) => {
  const { proc: backendProc, base: BASE } = await sobeBackend({ token: SESSION_TOKEN });
  t.after(() => backendProc.kill());

  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-home-"));
  const cliProc = spawn("node", ["src/pair-cli.js"], {
    cwd: AGENT_ROOT,
    env: { ...process.env, HOME: fakeHome, JARVIS_BACKEND_URL: BASE, JARVIS_AGENT_NAME: "PC-CLI-TEST" },
  });
  t.after(() => cliProc.kill());

  let stdout = "";
  let stderr = "";
  let confirmed = false;
  cliProc.stdout.on("data", (chunk) => {
    stdout += chunk.toString();
    if (!confirmed) {
      const m = stdout.match(/Código: ([A-Z0-9]{4}-[A-Z0-9]{4})/);
      if (m) {
        confirmed = true;
        fetchTeimoso(`${BASE}/api/pair/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Backend-Token": SESSION_TOKEN },
          body: JSON.stringify({ user_code: m[1] }),
        }).catch(() => {});
      }
    }
  });
  cliProc.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

  const exitCode = await new Promise((resolve) => cliProc.on("exit", resolve));

  assert.ok(confirmed, "o código apareceu no stdout e foi confirmado");
  assert.match(stdout, /Código: [A-Z0-9]{4}-[A-Z0-9]{4}/, "mostrou o código de pareamento");

  if (exitCode === 0) {
    // Cofre do SO disponível de verdade (ex.: Windows CI com Credential
    // Manager) — o pareamento completa de ponta a ponta.
    assert.match(stdout, /Pareado com sucesso/, "cofre disponível: deveria completar com sucesso");
    assert.equal(stderr, "", "sucesso não deveria escrever nada em stderr");
  } else {
    // Cofre indisponível (aqui: Linux sem libsecret) — falha ALTA e CLARA,
    // nunca um crash genérico ou silencioso.
    assert.equal(exitCode, 1);
    assert.doesNotMatch(stdout, /Pareado com sucesso/);
    assert.match(stderr, /Falha no pareamento/);
    assert.match(stderr, /cofre de credenciais/i, "erro é o do token-vault (esperado), não outra coisa");
  }
});
