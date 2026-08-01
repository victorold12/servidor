/**
 * Atalhos — um comando dispara várias ações. "modo foco" fecha o Discord,
 * silencia o volume e abre o que você usa pra estudar.
 *
 * ---------------------------------------------------------------------------
 * A REGRA QUE FAZ ISTO SER SEGURO
 *
 * O comando `atalho_run` recebe um NOME, nunca uma lista de ações.
 *
 * Essa distinção é a coisa toda. Se o backend pudesse mandar os passos, um
 * atalho seria só um envelope: bastaria embrulhar qualquer ação nele pra
 * atravessar o gate com um pedido que parece inocente. Recebendo só o nome, o
 * pior que um backend comprometido consegue é disparar um atalho que o Victor
 * JÁ escreveu no disco dele — o mesmo poder de quem aperta um botão que já
 * existe na tela.
 *
 * E os passos continuam passando pelo gate um a um, na hora de rodar. O atalho
 * não é uma permissão; é uma lista de pedidos. Fechar o Discord pergunta se
 * fechar o Discord perguntaria sozinho.
 *
 * ---------------------------------------------------------------------------
 * O QUE AINDA NÃO EXISTE
 *
 * O app anterior (VTZ 1.11) tinha passos de `volume`. Aqui não: mexer no
 * volume no Windows sem dependência nativa exige truque (SendKeys, nircmd,
 * COM), e nenhum deles é confiável o bastante pra entrar num caminho que roda
 * sozinho. Um passo que às vezes funciona é pior que um passo ausente — some
 * na hora errada e ninguém sabe por quê. Os tipos suportados estão em
 * TIPOS_SUPORTADOS, e o que não estiver ali é recusado ao SALVAR, não ao rodar:
 * descobrir que o atalho tem um passo inválido no meio da execução seria
 * descobrir tarde.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { leJsonConfig } from "./json-config.js";

function baseDir() {
  return process.env.JARVIS_AGENT_DIR || path.join(os.homedir(), ".jarvis-agente");
}
function arquivo() { return path.join(baseDir(), "atalhos.json"); }

/** Cada tipo aqui tem um handler correspondente no command-dispatcher. */
export const TIPOS_SUPORTADOS = {
  app: new Set(["abrir", "fechar"]),
  url: new Set(["abrir"]),
};

/* Exemplos que aparecem no primeiro uso. Não são "configuração padrão": são
   uma demonstração do formato, pra a pessoa não ter que adivinhar a forma do
   JSON pra criar o dela. */
export const EXEMPLOS = {
  "modo foco": [
    { type: "app", action: "fechar", target: "discord" },
    { type: "app", action: "abrir", target: "vscode" },
  ],
  "modo navegar": [
    { type: "app", action: "abrir", target: "navegador" },
  ],
};

export function carregaAtalhos() {
  const d = leJsonConfig(arquivo());
  if (d && typeof d === "object" && Object.keys(d).length) return d;
  return { ...EXEMPLOS };
}

/**
 * Valida a forma de um atalho. Devolve `{ ok, erro }`.
 *
 * Recusar no salvamento e não na execução é de propósito: um passo inválido
 * descoberto no meio de um macro deixa o PC num estado pela metade, com parte
 * das ações feitas e nenhuma explicação de por que parou.
 */
export function validaPassos(passos) {
  if (!Array.isArray(passos) || !passos.length) return { ok: false, erro: "atalho sem passos" };
  if (passos.length > 20) return { ok: false, erro: "atalho com passos demais (máximo 20)" };
  for (const [i, p] of passos.entries()) {
    const acoes = TIPOS_SUPORTADOS[p?.type];
    if (!acoes) {
      return { ok: false, erro: `passo ${i + 1}: tipo "${p?.type}" não existe (use: ${Object.keys(TIPOS_SUPORTADOS).join(", ")})` };
    }
    if (!acoes.has(p?.action)) {
      return { ok: false, erro: `passo ${i + 1}: ação "${p?.action}" não vale pra "${p.type}" (use: ${[...acoes].join(", ")})` };
    }
    if (!String(p?.target || "").trim()) return { ok: false, erro: `passo ${i + 1}: falta o alvo` };
  }
  return { ok: true };
}

export function salvaAtalho(nome, passos) {
  const limpo = String(nome || "").trim().toLowerCase();
  if (!limpo) return { ok: false, erro: "atalho sem nome" };
  const v = validaPassos(passos);
  if (!v.ok) return v;

  const todos = carregaAtalhos();
  todos[limpo] = passos;
  fs.mkdirSync(baseDir(), { recursive: true });
  fs.writeFileSync(arquivo(), JSON.stringify(todos, null, 2), { mode: 0o600 });
  return { ok: true, nome: limpo, passos: passos.length };
}

export function apagaAtalho(nome) {
  const limpo = String(nome || "").trim().toLowerCase();
  const todos = carregaAtalhos();
  if (!todos[limpo]) return { ok: false, erro: `não existe atalho "${limpo}"` };
  delete todos[limpo];
  fs.mkdirSync(baseDir(), { recursive: true });
  fs.writeFileSync(arquivo(), JSON.stringify(todos, null, 2), { mode: 0o600 });
  return { ok: true };
}

/** Acha o atalho pelo nome, tolerando caixa e espaços. */
export function resolveAtalho(nome, todos = carregaAtalhos()) {
  const alvo = String(nome || "").trim().toLowerCase().replace(/\s+/g, " ");
  if (!alvo) return null;
  if (todos[alvo]) return { nome: alvo, passos: todos[alvo] };
  for (const [k, v] of Object.entries(todos)) {
    if (k.toLowerCase().replace(/\s+/g, " ") === alvo) return { nome: k, passos: v };
  }
  return null;
}
