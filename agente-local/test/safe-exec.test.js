/**
 * Testes da máquina de decisão + execução sem shell.
 * Usa comandos reais inofensivos (echo, whoami). Para Tier 3, usa um comando de
 * blocklist que NÃO existe como binário (diskpart no Linux) — assim dá pra
 * verificar o gate sem risco de executar algo destrutivo.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { runCommand } from "../src/safe-exec.js";
import { TIER } from "../src/tier-validator.js";

test("Tier 1 (allowlist) roda automático e retorna stdout", async () => {
  const r = await runCommand({ command: "echo ola-jarvis" });
  assert.equal(r.ok, true);
  assert.equal(r.decision, "auto");
  assert.equal(r.tier, TIER.WRITE);
  assert.match(r.stdout, /ola-jarvis/);
  assert.equal(r.audit.result, "ok");
});

test("Tier 2 SEM confirmFn é negado (fail-safe: sem UI, não roda)", async () => {
  const r = await runCommand({ command: "whoami" });
  assert.equal(r.ok, false);
  assert.equal(r.decision, "denied");
  assert.match(r.error, /confirmação local/);
});

test("Tier 2 com confirmFn='deny' não executa", async () => {
  let asked = false;
  const r = await runCommand({
    command: "whoami",
    confirmFn: async () => { asked = true; return "deny"; },
  });
  assert.equal(asked, true, "deve ter pedido confirmação");
  assert.equal(r.ok, false);
  assert.equal(r.decision, "denied");
});

test("Tier 2 com confirmFn='once' executa e audita como confirmado", async () => {
  const r = await runCommand({
    command: "whoami",
    confirmFn: async () => "once",
  });
  assert.equal(r.ok, true);
  assert.equal(r.decision, "confirmed");
  assert.equal(r.audit.decision, "confirmed");
});

test("confirmFn recebe o comando CRU exato (a última defesa é ler isso)", async () => {
  let seen = null;
  await runCommand({
    command: "algum-binario --perigoso",
    confirmFn: async (info) => { seen = info; return "deny"; },
  });
  assert.equal(seen.command, "algum-binario --perigoso");
  assert.equal(seen.tier, TIER.CONFIRM);
});

test("Tier 3 (blocklist) é bloqueado e NÃO executa, mesmo com confirmFn dizendo sim", async () => {
  let asked = false;
  const r = await runCommand({
    command: "rm -rf /",
    confirmFn: async () => { asked = true; return "always"; },
  });
  assert.equal(r.ok, false);
  assert.equal(r.decision, "denied");
  assert.equal(asked, false, "Tier 3 nunca deve nem perguntar — bloqueia antes");
  assert.match(r.error, /bloqueado/);
});

test("Tier 3 só passa do gate se explicitamente liberado (isUnlocked)", async () => {
  // 'diskpart' bate na blocklist. No Linux o binário não existe, então com
  // unlock o gate passa e a execução falha com erro de SO — provando que o
  // gate liberou (não bloqueou por política).
  const r = await runCommand({
    command: "diskpart",
    isUnlocked: () => true,
  });
  assert.equal(r.ok, false);
  // erro NÃO é "bloqueado" (política), e sim de execução (binário ausente).
  assert.doesNotMatch(r.error, /bloqueado/);
});

test("comando com metacaractere de shell nunca cai pra shell:true", async () => {
  // '&&' sobe pra Tier 2; mesmo confirmando, parseCommand recusa (null) e não roda.
  const r = await runCommand({
    command: "echo a && echo b",
    confirmFn: async () => "once",
  });
  assert.equal(r.ok, false);
  assert.match(r.error, /shell/);
});
