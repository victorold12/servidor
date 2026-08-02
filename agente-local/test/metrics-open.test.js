/**
 * Duas ações novas com riscos opostos.
 *
 * sys_metrics é leitura pura de contadores do SO — se PERGUNTAR alguma coisa, a
 * tela de CPU/RAM vira um interrogatório a cada atualização e ninguém usa.
 *
 * open_url é o contrário: abrir link parece inofensivo e não é. Um link pode ser
 * phishing ou download, e o pedido nasce de um modelo. Aqui trava-se que ele
 * SEMPRE passa pela confirmação local, que só http/https entram, e que a
 * liberação "sempre" vale por SITE — liberar um link do youtube.com não pode
 * abrir a porta pra qualquer endereço do mundo.
 */
/* Isolamento do diretório do agente.
 *
 * A memória de aprovações (aprovacoes.js) grava em disco, e o gate agora a
 * consulta. Sem redirecionar, o teste escreveria no perfil REAL do usuário e
 * uma aprovação lembrada vazaria de um caso pro seguinte — foi assim que este
 * arquivo passou a falhar com "perguntou de novo pro mesmo site: 0 !== 1",
 * porque a resposta já estava guardada e ninguém perguntou nada.
 *
 * Mesma convenção do stt.js e do listener.js. */
process.env.JARVIS_AGENT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-cmd-"));

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { createCommandHandler } from "../src/command-dispatcher.js";

function monta({ decisao = "once" } = {}) {
  const perguntas = [];
  const auditoria = [];
  const handler = createCommandHandler({
    getAllowedRoots: () => [],
    confirmFn: async (info) => { perguntas.push(info); return decisao; },
    sendAudit: (e) => auditoria.push(e),
    isUnlocked: () => false,
    // arquivo de verdade: recordAudit grava em disco e nao aceita caminho nulo
    auditFilePath: path.join(fs.mkdtempSync(path.join(os.tmpdir(), "vtz-mo-")), "audit.jsonl"),
  });
  return { handler, perguntas, auditoria };
}

test("sys_metrics devolve CPU, RAM e plataforma sem perguntar nada", async () => {
  const { handler, perguntas } = monta();
  const r = await handler({ action: "sys_metrics" });

  assert.equal(r.ok, true);
  assert.equal(perguntas.length, 0, "leitura de contador do SO não pode pedir confirmação");
  assert.equal(typeof r.data.ram_total_bytes, "number");
  assert.ok(r.data.ram_total_bytes > 0);
  assert.ok(r.data.ram_pct >= 0 && r.data.ram_pct <= 100, r.data.ram_pct);
  assert.equal(typeof r.data.cpu_nucleos, "number");
  assert.ok(r.data.plataforma.length > 0);
});

test("o percentual de CPU aparece a partir da segunda leitura", async () => {
  const { handler } = monta();
  const um = await handler({ action: "sys_metrics" });

  /* Trabalho de verdade entre os dois retratos. Sem isso os contadores do SO
     não avançam, o delta dá zero e não há o que dividir — a segunda leitura
     também viria sem percentual. Rodando a suíte inteira as chamadas ficam
     coladas e o teste virava sorteio; foi assim que ele falhou junto e passou
     sozinho. */
  const ate = Date.now() + 30;
  let n = 0;
  while (Date.now() < ate) n += Math.sqrt(n + 1);
  assert.ok(n > 0);

  const dois = await handler({ action: "sys_metrics" });

  // Um retrato só daria a média desde o boot — número que nunca muda.
  if (um.data.cpu_pct === null) assert.match(um.data.aviso, /primeira leitura/);
  assert.equal(typeof dois.data.cpu_pct, "number", "a segunda leitura precisa ter percentual");
  assert.ok(dois.data.cpu_pct >= 0 && dois.data.cpu_pct <= 100, dois.data.cpu_pct);
  assert.equal(dois.data.aviso, null);
});

test("open_url só aceita http e https", async () => {
  const { handler, perguntas } = monta();
  for (const ruim of ["file:///C:/Windows/System32/config/SAM",
                      "javascript:alert(1)",
                      "ms-settings:privacy",
                      "data:text/html,<script>x</script>",
                      "não é url", ""]) {
    const r = await handler({ action: "open_url", args: { url: ruim } });
    assert.equal(r.ok, false, `deixou passar: ${ruim}`);
    assert.match(r.data.error, /http/);
  }
  assert.equal(perguntas.length, 0, "nem devia ter perguntado — a URL é inválida de saída");
});

test("open_url sempre passa pela confirmação local", async () => {
  const { handler, perguntas } = monta({ decisao: "deny" });
  const r = await handler({ action: "open_url", args: { url: "https://exemplo.test/pagina" } });

  assert.equal(r.ok, false);
  assert.equal(perguntas.length, 1, "abriu sem perguntar");
  assert.match(perguntas[0].command, /ABRIR https:\/\/exemplo\.test/);
  assert.equal(perguntas[0].tier, 2);
  assert.match(r.data.error, /negou/);
});

test('"sempre permitir" vale por SITE, não pra internet inteira', async () => {
  const { handler, perguntas } = monta({ decisao: "always" });
  await handler({ action: "open_url", args: { url: "https://youtube.com/watch?v=1" } });
  await handler({ action: "open_url", args: { url: "https://youtube.com/results?q=x" } });
  assert.equal(perguntas.length, 1, "perguntou de novo pro mesmo site");

  await handler({ action: "open_url", args: { url: "https://site-desconhecido.test/x" } });
  assert.equal(perguntas.length, 2,
    "liberar o youtube liberou um site diferente — a chave do cache está larga demais");
});

test("tudo que abre vai pra auditoria", async () => {
  const { handler, auditoria } = monta({ decisao: "deny" });
  await handler({ action: "open_url", args: { url: "https://exemplo.test/x" } });
  await handler({ action: "open_url", args: { url: "file:///etc/passwd" } });

  assert.equal(auditoria.length, 2, "faltou registrar alguma tentativa");
  assert.ok(auditoria.every((e) => e.action_type === "open_url"), auditoria);
  assert.ok(auditoria.some((e) => String(e.result).includes("negado")), auditoria);
  assert.ok(auditoria.some((e) => String(e.result).includes("http")), auditoria);
});

test("ação desconhecida continua sendo recusada", async () => {
  const { handler } = monta();
  const r = await handler({ action: "formatar_o_hd", args: {} });
  assert.notEqual(r.ok, true);
});
