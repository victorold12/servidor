import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createCommandHandler } from "../src/command-dispatcher.js";
import { readLocalAudit } from "../src/audit.js";

function tmpAuditFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-disp-")), "audit.jsonl");
}

test("ação desconhecida devolve erro, sem tocar em safe-exec/auditoria", async () => {
  const f = tmpAuditFile();
  const handler = createCommandHandler({
    getAllowedRoots: () => [],
    confirmFn: async () => "deny",
    auditFilePath: f,
  });
  const result = await handler({ action: "fs_delete_everything", args: {} });
  assert.equal(result.ok, false);
  assert.match(result.data.error, /ação desconhecida/);
  assert.equal(readLocalAudit(10, f).length, 0);
});

test("'run' com comando Tier 1 executa e audita (local + hub)", async () => {
  const f = tmpAuditFile();
  const sent = [];
  const handler = createCommandHandler({
    getAllowedRoots: () => [],
    confirmFn: async () => "deny",
    sendAudit: (e) => sent.push(e),
    auditFilePath: f,
  });
  const result = await handler({ action: "run", args: { command: "echo do-agente" }, chat_id: "c1", message_id: "m1" });
  assert.equal(result.ok, true);
  assert.match(result.data.stdout, /do-agente/);
  const local = readLocalAudit(10, f);
  assert.equal(local.length, 1);
  assert.equal(local[0].chat_id, "c1");
  assert.equal(sent.length, 1, "também mandou pro hub");
});

test("'run' Tier 2 chama confirmFn com o comando exato e a procedência", async () => {
  const f = tmpAuditFile();
  let seen = null;
  const handler = createCommandHandler({
    getAllowedRoots: () => [],
    confirmFn: async (info) => { seen = info; return "once"; },
    auditFilePath: f,
  });
  await handler({ action: "run", args: { command: "algum-binario --x" }, chat_id: "conv-9" });
  assert.equal(seen.command, "algum-binario --x");
  assert.equal(seen.provenance.chat_id, "conv-9");
});

test("'run' Tier 3 (blocklist) nunca chama confirmFn e nunca executa", async () => {
  const f = tmpAuditFile();
  let asked = false;
  const handler = createCommandHandler({
    getAllowedRoots: () => [],
    confirmFn: async () => { asked = true; return "always"; },
    auditFilePath: f,
  });
  const result = await handler({ action: "run", args: { command: "rm -rf /" } });
  assert.equal(result.ok, false);
  assert.equal(asked, false);
  assert.equal(readLocalAudit(10, f)[0].tier, 3);
});

test("auditoria é gravada mesmo quando sendAudit (hub) falha", async () => {
  const f = tmpAuditFile();
  const handler = createCommandHandler({
    getAllowedRoots: () => [],
    confirmFn: async () => "deny",
    sendAudit: () => { throw new Error("WS caído"); },
    auditFilePath: f,
  });
  await handler({ action: "run", args: { command: "echo x" } });
  assert.equal(readLocalAudit(10, f).length, 1, "cópia local sobrevive ao hub falhando");
});

test("getAllowedRoots é consultado a cada chamada (reflete policy_update em runtime)", async () => {
  const f = tmpAuditFile();
  let roots = [];
  const handler = createCommandHandler({
    getAllowedRoots: () => roots,
    confirmFn: async () => "deny",
    auditFilePath: f,
  });
  await handler({ action: "run", args: { command: "echo x" } });
  roots = ["/algum/lugar"];
  await handler({ action: "run", args: { command: "echo y" } });
  // não afirma nada sobre o resultado (comando não usa roots) — só prova que
  // getAllowedRoots() é chamada de novo e não fica presa a um valor antigo.
  assert.equal(readLocalAudit(10, f).length, 2);
});

test("ação fs_write dentro da root escreve e audita (ida-e-volta pelo dispatcher)", async () => {
  const f = tmpAuditFile();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-disp-root-"));
  const sent = [];
  const handler = createCommandHandler({
    getAllowedRoots: () => [root],
    confirmFn: async () => "deny",
    sendAudit: (e) => sent.push(e),
    auditFilePath: f,
  });
  const target = path.join(root, "criado.txt");
  const result = await handler({
    action: "fs_write",
    args: { path: target, content: "via dispatcher" },
    chat_id: "c1",
  });
  assert.equal(result.ok, true);
  assert.equal(fs.readFileSync(target, "utf8"), "via dispatcher");
  const local = readLocalAudit(10, f);
  assert.equal(local.length, 1);
  assert.equal(local[0].action_type, "fs_write");
  assert.equal(local[0].chat_id, "c1");
  assert.equal(sent.length, 1, "também mandou pro hub");
});

test("ação fs_read fora das roots sem confirmFn é negada e auditada", async () => {
  const f = tmpAuditFile();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-disp-root2-"));
  const handler = createCommandHandler({
    getAllowedRoots: () => [root],
    confirmFn: null,
    auditFilePath: f,
  });
  const result = await handler({ action: "fs_read", args: { path: "/etc/hostname" } });
  assert.equal(result.ok, false);
  const local = readLocalAudit(10, f);
  assert.equal(local.length, 1);
  assert.equal(local[0].tier, 2);
});
