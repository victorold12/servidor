import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { appendLocalAudit, readLocalAudit, recordAudit } from "../src/audit.js";

function tmpFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-audit-")), "audit.jsonl");
}

test("appendLocalAudit grava JSONL, uma linha por chamada", () => {
  const f = tmpFile();
  appendLocalAudit({ action_type: "run", target: "echo a", tier: 1, decision: "auto", result: "ok" }, f);
  appendLocalAudit({ action_type: "run", target: "echo b", tier: 1, decision: "auto", result: "ok" }, f);
  const lines = fs.readFileSync(f, "utf8").trim().split("\n");
  assert.equal(lines.length, 2);
  assert.equal(JSON.parse(lines[0]).target, "echo a");
  assert.equal(JSON.parse(lines[1]).target, "echo b");
});

test("appendLocalAudit funciona mesmo se o arquivo/pasta ainda não existir", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-audit-"));
  const f = path.join(dir, "novo.jsonl");
  assert.doesNotThrow(() => appendLocalAudit({ action_type: "run" }, f));
  assert.equal(readLocalAudit(10, f).length, 1);
});

test("readLocalAudit sem arquivo devolve [] (não lança)", () => {
  const f = path.join(os.tmpdir(), "jarvis-nao-existe-" + Date.now() + ".jsonl");
  assert.deepEqual(readLocalAudit(10, f), []);
});

test("readLocalAudit respeita o limite, pegando os mais recentes", () => {
  const f = tmpFile();
  for (let i = 0; i < 5; i++) appendLocalAudit({ action_type: "run", target: `cmd-${i}` }, f);
  const last2 = readLocalAudit(2, f);
  assert.equal(last2.length, 2);
  assert.deepEqual(last2.map((e) => e.target), ["cmd-3", "cmd-4"]);
});

test("recordAudit grava local E manda pro hub quando sendToHub existe", () => {
  const f = tmpFile();
  const sent = [];
  recordAudit({ entry: { action_type: "run", target: "x" }, sendToHub: (e) => sent.push(e), filePath: f });
  assert.equal(readLocalAudit(10, f).length, 1, "gravou local");
  assert.equal(sent.length, 1, "mandou pro hub");
});

test("recordAudit: sendToHub falhando NÃO perde o registro local (Seção 10)", () => {
  const f = tmpFile();
  assert.doesNotThrow(() =>
    recordAudit({
      entry: { action_type: "run", target: "x" },
      sendToHub: () => { throw new Error("WS caído"); },
      filePath: f,
    })
  );
  assert.equal(readLocalAudit(10, f).length, 1, "cópia local sobrevive mesmo com hub fora do ar");
});

test("recordAudit sem sendToHub (offline) só grava local, sem lançar", () => {
  const f = tmpFile();
  assert.doesNotThrow(() => recordAudit({ entry: { action_type: "run", target: "x" }, filePath: f }));
  assert.equal(readLocalAudit(10, f).length, 1);
});
