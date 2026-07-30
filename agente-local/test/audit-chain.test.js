/**
 * Testes da cadeia de hash do log de auditoria LOCAL (verifyLocalChain).
 * Espelha o teste do backend (tests/test_audit_chain.py), mas pro arquivo JSONL.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { appendLocalAudit, verifyLocalChain, readLocalAudit } from "../src/audit.js";

function tmpFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-chain-")), "audit.jsonl");
}

test("cada linha encadeia: 1ª aponta pro genesis, seguintes pro hash anterior", () => {
  const f = tmpFile();
  appendLocalAudit({ action_type: "run", target: "a" }, f);
  appendLocalAudit({ action_type: "run", target: "b" }, f);
  appendLocalAudit({ action_type: "run", target: "c" }, f);
  const lines = readLocalAudit(10, f);
  assert.equal(lines[0].prev_hash, "0".repeat(64));
  assert.equal(lines[1].prev_hash, lines[0].hash);
  assert.equal(lines[2].prev_hash, lines[1].hash);
});

test("verifyLocalChain passa numa cadeia íntegra", () => {
  const f = tmpFile();
  for (let i = 0; i < 4; i++) appendLocalAudit({ action_type: "run", target: `t${i}` }, f);
  const res = verifyLocalChain(f);
  assert.equal(res.ok, true);
  assert.equal(res.chained, 4);
});

test("adulterar um campo no meio é detectado", () => {
  const f = tmpFile();
  for (let i = 0; i < 3; i++) appendLocalAudit({ action_type: "run", target: `t${i}` }, f);
  // reescreve a 2ª linha com target trocado, mantendo o hash antigo (adulteração)
  const lines = fs.readFileSync(f, "utf8").split("\n").filter(Boolean);
  const tampered = JSON.parse(lines[1]);
  tampered.target = "HACKEADO";
  lines[1] = JSON.stringify(tampered);
  fs.writeFileSync(f, lines.join("\n") + "\n");
  const res = verifyLocalChain(f);
  assert.equal(res.ok, false);
  assert.equal(res.brokenAt, 1);
});

test("remover uma linha do meio é detectado", () => {
  const f = tmpFile();
  for (let i = 0; i < 3; i++) appendLocalAudit({ action_type: "run", target: `t${i}` }, f);
  const lines = fs.readFileSync(f, "utf8").split("\n").filter(Boolean);
  lines.splice(1, 1); // apaga a do meio
  fs.writeFileSync(f, lines.join("\n") + "\n");
  const res = verifyLocalChain(f);
  assert.equal(res.ok, false);
  assert.equal(res.brokenAt, 1, "a linha que era a 3ª agora está na posição 1 e seu prev_hash não bate");
});

test("linhas legadas sem hash são puladas e o resto verifica", () => {
  const f = tmpFile();
  // 2 linhas legadas (formato antigo, sem prev_hash/hash)
  fs.writeFileSync(f, JSON.stringify({ action_type: "run", target: "old0" }) + "\n" +
    JSON.stringify({ action_type: "run", target: "old1" }) + "\n");
  // agora appends novos encadeiam (lastHashOf lê a última linha: sem hash -> genesis)
  appendLocalAudit({ action_type: "run", target: "new0" }, f);
  appendLocalAudit({ action_type: "run", target: "new1" }, f);
  const res = verifyLocalChain(f);
  assert.equal(res.ok, true);
  assert.equal(res.legacy, 2);
  assert.equal(res.chained, 2);
});

test("verifyLocalChain sem arquivo devolve ok vazio (não lança)", () => {
  const f = path.join(os.tmpdir(), "jarvis-chain-nao-existe-" + Date.now() + ".jsonl");
  const res = verifyLocalChain(f);
  assert.deepEqual(res, { ok: true, count: 0, chained: 0, legacy: 0 });
});
