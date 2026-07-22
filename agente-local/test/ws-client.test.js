/**
 * Teste PURO (sem rede) do cliente WS: WebSocket falso injetado + timers
 * mockados. Cobre a lógica que o teste de integração não consegue exercitar
 * de forma determinística (backoff crescente, parada em 4401, heartbeat).
 * Ver ws-client.integration.test.js pro contrato real de fio.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createAgentConnection } from "../src/ws-client.js";

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this._listeners = {};
    FakeWebSocket.instances.push(this);
  }
  addEventListener(type, fn) {
    (this._listeners[type] ??= []).push(fn);
  }
  _emit(type, ev = {}) {
    for (const fn of this._listeners[type] || []) fn(ev);
  }
  send(data) {
    if (this.readyState !== FakeWebSocket.OPEN) throw new Error("send com socket fechado");
    this.sent.push(data);
  }
  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this._emit("close", { code: 1000 });
  }
  // ---- helpers de teste (o "servidor" simulado) ----
  _open() {
    this.readyState = FakeWebSocket.OPEN;
    this._emit("open");
  }
  _receive(obj) {
    this._emit("message", { data: JSON.stringify(obj) });
  }
  _serverClose(code) {
    this.readyState = FakeWebSocket.CLOSED;
    this._emit("close", { code });
  }
}
FakeWebSocket.instances = [];

function lastSocket() {
  return FakeWebSocket.instances.at(-1);
}

function makeConn(t, overrides = {}) {
  FakeWebSocket.instances.length = 0;
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const events = [];
  const conn = createAgentConnection({
    backendUrl: "https://backend.exemplo",
    token: "tok-123",
    onCommand: async () => ({ ok: true, data: null }),
    onEvent: (e) => events.push(e),
    heartbeatMs: 10_000,
    WebSocketImpl: FakeWebSocket,
    ...overrides,
  });
  return { conn, events };
}

test("converte https-> wss e injeta o token na query", (t) => {
  const { conn } = makeConn(t);
  assert.equal(lastSocket().url, "wss://backend.exemplo/ws/agent?token=tok-123");
  conn.close();
});

test("manda heartbeat no intervalo configurado, só depois de open", async (t) => {
  const { conn } = makeConn(t, { heartbeatMs: 1000 });
  const sock = lastSocket();
  t.mock.timers.tick(5000);
  assert.equal(sock.sent.length, 0, "sem heartbeat antes de abrir");

  sock._open();
  t.mock.timers.tick(1000);
  assert.deepEqual(JSON.parse(sock.sent[0]), { type: "heartbeat" });
  t.mock.timers.tick(1000);
  assert.equal(sock.sent.length, 2, "heartbeat repete a cada intervalo");
  conn.close();
});

test("despacha 'command' pro onCommand e devolve 'result' com o mesmo id", async (t) => {
  const { conn } = makeConn(t, {
    onCommand: async (msg) => ({ ok: true, data: { echo: msg.action } }),
  });
  const sock = lastSocket();
  sock._open();
  sock._receive({ type: "command", id: "cmd-1", action: "listar" });
  await new Promise((r) => setImmediate(r)); // deixa a promise de handleCommand resolver

  const sent = JSON.parse(sock.sent.at(-1));
  assert.deepEqual(sent, { type: "result", id: "cmd-1", ok: true, data: { echo: "listar" } });
  conn.close();
});

test("onCommand que lança erro vira result ok:false, não derruba o cliente", async (t) => {
  const { conn } = makeConn(t, {
    onCommand: async () => { throw new Error("boom"); },
  });
  const sock = lastSocket();
  sock._open();
  sock._receive({ type: "command", id: "cmd-2", action: "x" });
  await new Promise((r) => setImmediate(r));

  const sent = JSON.parse(sock.sent.at(-1));
  assert.equal(sent.type, "result");
  assert.equal(sent.ok, false);
  assert.match(sent.data.error, /boom/);
  conn.close();
});

test("'revoked' fecha e NÃO agenda reconexão", async (t) => {
  const { conn, events } = makeConn(t);
  const sock = lastSocket();
  sock._open();
  sock._receive({ type: "revoked" });

  const countBefore = FakeWebSocket.instances.length;
  t.mock.timers.tick(60_000); // tempo de sobra pra qualquer backoff possível
  assert.equal(FakeWebSocket.instances.length, countBefore, "não deve ter criado nova conexão");
  assert.ok(events.some((e) => e.type === "revoked"));
  conn.close();
});

test("close code=4401 para de reconectar (token morto) e emite 'unauthorized'", async (t) => {
  const { conn, events } = makeConn(t);
  const sock = lastSocket();
  sock._open();
  sock._serverClose(4401);

  const countBefore = FakeWebSocket.instances.length;
  t.mock.timers.tick(60_000);
  assert.equal(FakeWebSocket.instances.length, countBefore, "4401 não deve reconectar");
  assert.ok(events.some((e) => e.type === "unauthorized"));
  conn.close();
});

test("close com outro code reconecta, com backoff crescente entre tentativas", async (t) => {
  const { conn, events } = makeConn(t);
  let sock = lastSocket();
  sock._open();
  sock._serverClose(1006); // queda de rede, não auth

  const first = events.find((e) => e.type === "reconnecting");
  assert.ok(first, "deve agendar reconexão");
  assert.equal(first.attempt, 1);
  t.mock.timers.tick(first.inMs);
  assert.equal(FakeWebSocket.instances.length, 2, "abriu uma nova conexão após o delay");

  sock = lastSocket();
  sock._serverClose(1006); // falha de novo, imediatamente
  const second = events.filter((e) => e.type === "reconnecting")[1];
  assert.equal(second.attempt, 2);
  assert.ok(second.inMs > first.inMs * 1.3, `backoff devia crescer: ${first.inMs} -> ${second.inMs}`);
  conn.close();
});

test("reconexão bem-sucedida zera o contador de tentativas", async (t) => {
  const { conn, events } = makeConn(t);
  let sock = lastSocket();
  sock._open();
  sock._serverClose(1006);
  const first = events.find((e) => e.type === "reconnecting");
  t.mock.timers.tick(first.inMs);

  sock = lastSocket();
  sock._open(); // reconectou com sucesso
  sock._serverClose(1006); // cai de novo

  const attempts = events.filter((e) => e.type === "reconnecting").map((e) => e.attempt);
  assert.deepEqual(attempts, [1, 1], "depois de abrir com sucesso, a próxima tentativa volta a ser #1");
  conn.close();
});

test("sendAudit só envia quando o socket está OPEN; não lança quando fechado", (t) => {
  const { conn } = makeConn(t);
  const sock = lastSocket();
  assert.doesNotThrow(() => conn.sendAudit({ action_type: "run" }));
  assert.equal(sock.sent.length, 0, "nada enviado antes de abrir");

  sock._open();
  conn.sendAudit({ action_type: "run", target: "echo hi" });
  const sent = JSON.parse(sock.sent.at(-1));
  assert.equal(sent.type, "audit");
  assert.equal(sent.target, "echo hi");
  conn.close();
});

test("close() do lado do cliente não agenda reconexão", (t) => {
  const { conn } = makeConn(t);
  const sock = lastSocket();
  sock._open();
  conn.close();
  const countBefore = FakeWebSocket.instances.length;
  t.mock.timers.tick(60_000);
  assert.equal(FakeWebSocket.instances.length, countBefore);
});
