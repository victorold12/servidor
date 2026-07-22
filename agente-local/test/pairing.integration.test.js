/**
 * Teste de INTEGRAÇÃO REAL: sobe o backend Python de verdade (uvicorn, num
 * banco temporário isolado) e roda o cliente de pareamento Node contra ele.
 * Não é mock — é a fronteira Node↔Python mais arriscada do projeto (o próprio
 * contrato HTTP do fluxo RFC 8628), então vale testar como processo separado.
 *
 * Precisa de `python3 -m uvicorn` disponível (mesmo ambiente do backend).
 * Se o backend não subir a tempo, o teste falha com uma mensagem clara em vez
 * de travar — não usa sleep-loop indefinido.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { pairWithBackend } from "../src/pairing.js";

const PORT = 8799;
const BASE = `http://127.0.0.1:${PORT}`;
const SESSION_TOKEN = "test-session-token";
const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");

async function waitForHealth(tries = 60) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(`${BASE}/api/health`);
      if (r.ok) return;
    } catch {
      /* backend ainda subindo */
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`backend não respondeu em ${BASE}/api/health a tempo`);
}

test("pairing.js: fluxo RFC 8628 completo contra o backend Python real", async (t) => {
  const dbPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-int-")), "test.db");
  const proc = spawn(
    "python3",
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(PORT)],
    { cwd: REPO_ROOT, env: { ...process.env, BACKEND_TOKEN: SESSION_TOKEN, JARVIS_DB_PATH: dbPath }, stdio: "ignore" }
  );
  t.after(() => proc.kill());

  await waitForHealth();

  // Simula o navegador confirmando assim que o código aparece — igual você
  // digitando o user_code na tela "Parear dispositivo" do site.
  const result = await pairWithBackend({
    backendUrl: BASE,
    name: "PC-TEST",
    platform: "linux",
    onEvent: (evt) => {
      if (evt.type === "code") {
        fetch(`${BASE}/api/pair/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Backend-Token": SESSION_TOKEN },
          body: JSON.stringify({ user_code: evt.userCode }),
        }).catch(() => {}); // se falhar, o teste vai estourar no timeout do poll — visível o bastante
      }
    },
  });

  assert.ok(result.agentId, "recebeu agent_id");
  assert.ok(result.agentToken.length > 30, "recebeu agent_token de verdade");
  assert.deepEqual(result.allowedRoots, []);

  // O token funciona de verdade pro hub WS (não só "parece certo")?
  const wsRes = await new Promise((resolve) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws/agent?token=${result.agentToken}`);
    ws.addEventListener("open", () => { ws.close(); resolve("open"); });
    ws.addEventListener("error", () => resolve("error"));
    setTimeout(() => resolve("timeout"), 5000);
  });
  assert.equal(wsRes, "open", "o token emitido no pareamento autentica no /ws/agent de verdade");

  // Token inválido: o hub ACEITA e só então fecha com code=4401 (de propósito
  // — ver comentário em agents_hub.py). É esse code que ws-client.js usa pra
  // decidir "não adianta reconectar". Trava o contrato aqui, no cliente real,
  // não só no lado Python — é exatamente esta borda Node↔Python que já
  // escondeu um bug (fechar pré-accept não entregava code nenhum ao Node).
  const closeCode = await new Promise((resolve) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws/agent?token=token-invalido`);
    ws.addEventListener("close", (ev) => resolve(ev.code));
    setTimeout(() => resolve(null), 5000);
  });
  assert.equal(closeCode, 4401, "token inválido: close chega com code=4401 no cliente Node real");
});

test("pairWithBackend: user_code errado propositalmente deixa o agente pendente (não falha sozinho)", async (t) => {
  const dbPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-int-")), "test.db");
  const port = PORT + 1;
  const base = `http://127.0.0.1:${port}`;
  const proc = spawn(
    "python3",
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: REPO_ROOT, env: { ...process.env, BACKEND_TOKEN: SESSION_TOKEN, JARVIS_DB_PATH: dbPath }, stdio: "ignore" }
  );
  t.after(() => proc.kill());

  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) break;
    } catch {
      /* ainda subindo */
    }
    await new Promise((r) => setTimeout(r, 250));
  }

  const controller = new AbortController();
  const pairPromise = pairWithBackend({
    backendUrl: base,
    name: "PC-TEST2",
    platform: "linux",
    signal: controller.signal,
    onEvent: () => {}, // não confirma de propósito
  });

  // Deixa 1 ciclo de poll acontecer (confirma que fica "pending", não trava/erra sozinho)
  await new Promise((r) => setTimeout(r, 3500));
  controller.abort();
  await assert.rejects(pairPromise, /cancelado/);
});
