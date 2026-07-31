/**
 * Integração real: pareia contra o backend Python de verdade, conecta o
 * ws-client, e prova a travessia completa comando: POST /api/agents/{id}/command
 * (lado "navegador") -> hub -> WS -> onCommand no cliente -> WS -> hub resolve
 * a promise pendente -> resposta HTTP. É o caminho mais valioso pra testar
 * porque nenhum lado sozinho garante que os dois se encaixam.
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { pairWithBackend } from "../src/pairing.js";
import { createAgentConnection } from "../src/ws-client.js";
import { sobeBackend, fetchTeimoso } from "./_backend.js";

const SESSION_TOKEN = "test-session-token";
const SESSION_HEADERS = { "Content-Type": "application/json", "X-Backend-Token": SESSION_TOKEN };

async function pairFreshAgent(BASE, name) {
  return pairWithBackend({
    backendUrl: BASE,
    name,
    platform: "linux",
    onEvent: (evt) => {
      if (evt.type === "code") {
        fetchTeimoso(`${BASE}/api/pair/confirm`, {
          method: "POST",
          headers: SESSION_HEADERS,
          body: JSON.stringify({ user_code: evt.userCode }),
        }).catch(() => {});
      }
    },
  });
}

test("comando disparado pelo backend chega no cliente e a resposta volta pelo HTTP", async (t) => {
  const { proc, base: BASE } = await sobeBackend({ token: SESSION_TOKEN });
  t.after(() => proc.kill());

  const { agentId, agentToken } = await pairFreshAgent(BASE, "PC-WSTEST");

  const receivedCommands = [];
  const conn = createAgentConnection({
    backendUrl: BASE,
    token: agentToken,
    onCommand: async (msg) => {
      receivedCommands.push(msg);
      return { ok: true, data: { listou: msg.args?.path ?? null } };
    },
  });
  t.after(() => conn.close());

  // dá tempo do WS abrir e o hub marcar o agente online
  await new Promise((r) => setTimeout(r, 500));
  const agentsRes = await fetchTeimoso(`${BASE}/api/agents`, { headers: SESSION_HEADERS }).then((r) => r.json());
  assert.equal(agentsRes.agents.find((a) => a.agent_id === agentId)?.online, true, "agente aparece online no /api/agents");

  // "test_echo" é sintético — só prova o transporte. O vocabulário real de
  // ações (fs_read, run, etc.) é decidido no dispatcher de index.js, que fica
  // em cima disto e roteia pro safe-exec.js já testado.
  const cmdRes = await fetchTeimoso(`${BASE}/api/agents/${agentId}/command`, {
    method: "POST",
    headers: SESSION_HEADERS,
    body: JSON.stringify({ action: "test_echo", args: { path: "Downloads" } }),
  });
  assert.equal(cmdRes.status, 200, "backend respondeu 200 pro comando");
  const cmdData = await cmdRes.json();
  assert.equal(cmdData.ok, true);
  assert.deepEqual(cmdData.data, { listou: "Downloads" });
  assert.equal(receivedCommands.length, 1);
  assert.equal(receivedCommands[0].action, "test_echo");
});

test("revogar o agente enquanto conectado entrega 'revoked' pro cliente", async (t) => {
  const { proc, base } = await sobeBackend({ token: SESSION_TOKEN });
  t.after(() => proc.kill());

  const { agentId, agentToken } = await pairWithBackend({
    backendUrl: base,
    name: "PC-REVOKE-TEST",
    platform: "linux",
    onEvent: (evt) => {
      if (evt.type === "code") {
        fetchTeimoso(`${base}/api/pair/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Backend-Token": SESSION_TOKEN },
          body: JSON.stringify({ user_code: evt.userCode }),
        }).catch(() => {});
      }
    },
  });

  const events = [];
  const conn = createAgentConnection({
    backendUrl: base,
    token: agentToken,
    onCommand: async () => ({ ok: true }),
    onEvent: (e) => events.push(e),
  });
  t.after(() => conn.close());
  await new Promise((r) => setTimeout(r, 500));

  await fetchTeimoso(`${base}/api/agents/${agentId}/revoke`, {
    method: "POST",
    headers: { "X-Backend-Token": SESSION_TOKEN },
  });
  await new Promise((r) => setTimeout(r, 500));

  assert.ok(events.some((e) => e.type === "revoked"), "cliente recebeu a mensagem de revogação");
});
