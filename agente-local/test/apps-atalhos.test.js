/* Apps e atalhos — o teste existe pelo motivo de sempre neste projeto: a
 * funcionalidade é simpática ("abre o navegador", "modo foco") e a superfície
 * é a mais perigosa que existe aqui, porque termina em processo novo no PC.
 *
 * O que fica travado:
 *   - só roda o que está NO MAPA (caminho vindo da rede não vira processo)
 *   - atalho recebe NOME, nunca passos — senão vira envelope pra burlar o gate
 *   - fechar app pergunta; shell pergunta mesmo estando no mapa
 *   - cada passo do atalho passa pelo gate um a um
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-apps-"));
const AGENTE = process.env.JARVIS_AGENT_DIR;

const { resolveApp, precisaConfirmar, salvaApps } = await import("../src/apps.js");
const { validaPassos, resolveAtalho, salvaAtalho } = await import("../src/atalhos.js");
const { createCommandHandler } = await import("../src/command-dispatcher.js");

salvaApps({
  chrome: { exe: "C:\\Fake\\chrome.exe", aliases: ["navegador", "browser"] },
  spotify: { exe: "C:\\Fake\\spotify.exe", aliases: ["musica", "música"] },
  powershell: { exe: "C:\\Windows\\System32\\powershell.exe", aliases: ["shell"] },
});

test("resolve app por apelido, ignorando acento e caixa", () => {
  assert.equal(resolveApp("navegador")?.id, "chrome");
  assert.equal(resolveApp("NAVEGADOR")?.id, "chrome");
  /* whisper erra acento com frequência: quem fala "musica" quer "música". */
  assert.equal(resolveApp("musica")?.id, "spotify");
  assert.equal(resolveApp("música")?.id, "spotify");
  assert.equal(resolveApp("chrome")?.id, "chrome");
});

test("app fora do mapa não resolve", () => {
  assert.equal(resolveApp("C:\\Windows\\System32\\cmd.exe"), null);
  assert.equal(resolveApp("qualquer-coisa"), null);
  assert.equal(resolveApp(""), null);
});

test("shell e editor de registro exigem confirmação mesmo estando no mapa", () => {
  assert.equal(precisaConfirmar("powershell"), true);
  assert.equal(precisaConfirmar("cmd"), true);
  assert.equal(precisaConfirmar("regedit"), true);
  assert.equal(precisaConfirmar("spotify"), false);
});

test("atalho recusa passo de tipo inexistente ao SALVAR", () => {
  /* Recusar no salvamento e não na execução: um passo inválido descoberto no
     meio deixa o PC pela metade, com parte das ações feitas. */
  assert.match(validaPassos([{ type: "system", action: "volume", target: "0" }]).erro, /não existe/);
  assert.match(validaPassos([{ type: "app", action: "explodir", target: "x" }]).erro, /não vale/);
  assert.match(validaPassos([{ type: "app", action: "abrir", target: "" }]).erro, /alvo/);
  assert.equal(validaPassos([{ type: "app", action: "abrir", target: "chrome" }]).ok, true);
});

/* ================= o gate ================= */

function handlerDeTeste() {
  const perguntas = [];
  const auditoria = [];
  const h = createCommandHandler({
    getAllowedRoots: () => [AGENTE],
    confirmFn: async (info) => { perguntas.push(info.command); return "deny"; },
    sendAudit: (e) => auditoria.push(e),
    isUnlocked: () => false,
    auditFilePath: path.join(AGENTE, "audit.jsonl"),
  });
  return { h, perguntas, auditoria };
}

test("abrir app desconhecido é recusado e auditado", async () => {
  const { h, auditoria } = handlerDeTeste();
  const r = await h({ action: "app_open", args: { app: "C:\\Windows\\System32\\cmd.exe" } });
  assert.equal(r.ok, false);
  assert.match(r.data.error, /não conheço/);
  assert.ok(auditoria.some((e) => e.action_type === "app_open" && e.decision === "denied"),
    "recusa tem que ficar registrada");
});

test("fechar app pergunta antes", async () => {
  const { h, perguntas } = handlerDeTeste();
  const r = await h({ action: "app_close", args: { app: "spotify" } });
  assert.equal(r.ok, false, "confirmFn devolveu deny");
  assert.ok(perguntas.some((p) => /FECHAR spotify/.test(p)), perguntas);
});

test("abrir shell pergunta, mesmo estando no mapa", async () => {
  const { h, perguntas } = handlerDeTeste();
  await h({ action: "app_open", args: { app: "shell" } });
  assert.ok(perguntas.some((p) => /ABRIR powershell/.test(p)), perguntas);
});

/* ===== A propriedade central ===== */
test("atalho_run IGNORA passos vindos na mensagem", async () => {
  salvaAtalho("modo teste", [{ type: "app", action: "abrir", target: "spotify" }]);
  const { h, perguntas } = handlerDeTeste();

  /* Um backend comprometido tentando embrulhar uma ação própria no atalho.
     Se os passos da mensagem valessem, isto abriria um shell. */
  const r = await h({
    action: "atalho_run",
    args: {
      nome: "modo teste",
      passos: [{ type: "app", action: "abrir", target: "shell" }],
    },
  });

  assert.ok(!perguntas.some((p) => /powershell/.test(p)),
    "os passos da MENSAGEM não podem ter sido executados");
  assert.equal(r.data.atalho, "modo teste");
  assert.equal(r.data.passos.length, 1, "rodou só o passo salvo no disco");
});

test("atalho inexistente não roda nada", async () => {
  const { h, perguntas } = handlerDeTeste();
  const r = await h({ action: "atalho_run", args: { nome: "modo que nao existe" } });
  assert.equal(r.ok, false);
  assert.equal(perguntas.length, 0);
});

test("cada passo do atalho passa pelo gate, e um erro não para os outros", async () => {
  salvaAtalho("modo dois", [
    { type: "app", action: "fechar", target: "spotify" },   // vai perguntar -> deny
    { type: "app", action: "abrir", target: "inexistente" }, // não está no mapa
  ]);
  const { h, perguntas } = handlerDeTeste();
  const r = await h({ action: "atalho_run", args: { nome: "modo dois" } });

  assert.equal(r.ok, false);
  assert.equal(r.data.falhas, 2);
  assert.equal(r.data.passos.length, 2, "o segundo passo rodou mesmo com o primeiro falhando");
  assert.ok(perguntas.some((p) => /FECHAR spotify/.test(p)), "o passo passou pelo gate");
});

test("resolveAtalho tolera caixa e espaço extra", () => {
  salvaAtalho("modo foco", [{ type: "app", action: "abrir", target: "chrome" }]);
  assert.equal(resolveAtalho("  MODO   foco ")?.nome, "modo foco");
});
