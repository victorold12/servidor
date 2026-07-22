/**
 * Roda o pair-cli.js DE VERDADE (processo filho) contra o backend Python real,
 * confirmando pelo HTTP como o navegador faria. Prova a fiação completa:
 * prompt -> pairWithBackend -> mostra o código -> poll -> approved.
 *
 * Este ambiente não tem cofre de credenciais de SO (sem libsecret/D-Bus, sem
 * Windows/macOS) — então o teste espera exatamente onde ele DEVE falhar aqui:
 * em saveToken(), com a mensagem clara do token-vault, código de saída 1. Não
 * é um teste fraco "aceita qualquer erro" — verifica que é ESSE erro (cofre
 * indisponível), não um crash silencioso ou uma mensagem genérica.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const PORT = 8802;
const BASE = `http://127.0.0.1:${PORT}`;
const SESSION_TOKEN = "test-session-token";
const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");
const AGENT_ROOT = path.resolve(import.meta.dirname, "..");

async function waitForHealth() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`${BASE}/api/health`)).ok) return;
    } catch {
      /* subindo */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("backend não respondeu a tempo");
}

test("pair-cli.js: fluxo completo até o cofre do SO (que não existe neste ambiente) — falha alta e clara, não crash", async (t) => {
  const dbPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-int-")), "test.db");
  const backendProc = spawn(
    "python3",
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(PORT)],
    { cwd: REPO_ROOT, env: { ...process.env, BACKEND_TOKEN: SESSION_TOKEN, JARVIS_DB_PATH: dbPath }, stdio: "ignore" }
  );
  t.after(() => backendProc.kill());
  await waitForHealth();

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
        fetch(`${BASE}/api/pair/confirm`, {
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
  // Chegou a ponto de ter um agent_token de verdade (senão não haveria o que
  // salvar no cofre) — mas NÃO deve imprimir sucesso, porque falha antes disso.
  assert.doesNotMatch(stdout, /Pareado com sucesso/);
  assert.equal(exitCode, 1);
  assert.match(stderr, /Falha no pareamento/);
  assert.match(stderr, /cofre de credenciais/i, "erro é o do token-vault (esperado), não outra coisa");
});
