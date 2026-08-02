/**
 * Memória de aprovações — não perguntar dez vezes a mesma coisa.
 *
 * ---------------------------------------------------------------------------
 * O PROBLEMA QUE ELA RESOLVE, E POR QUE ELE É DE SEGURANÇA
 *
 * O gate de 4 camadas pede confirmação em Tier 2. Está certo. Mas quando a
 * mesma ação aparece dez vezes numa tarefa — abrir dez arquivos da mesma pasta,
 * rodar o mesmo comando em sequência — a décima confirmação não é analisada:
 * é clicada.
 *
 * Fadiga de aprovação não é incômodo, é falha de segurança. Um gate que
 * pergunta demais treina a pessoa a dizer sim sem ler, e aí ele para de
 * proteger exatamente no dia em que a pergunta era diferente.
 *
 * Este módulo troca "perguntar sempre" por "perguntar uma vez, com escopo e
 * prazo declarados".
 *
 * ---------------------------------------------------------------------------
 * POR QUE ELE MORA NO PC, E NÃO NO BACKEND
 *
 * `docs/SEGURANCA-AGENTE-LOCAL.md`: a decisão é SEMPRE tomada no PC, nunca pelo
 * backend. Uma memória de aprovações na nuvem seria um caminho para o servidor
 * conceder permissão — exatamente o que a arquitetura recusa. Ela vive em
 * disco local, no diretório do agente.
 *
 * ---------------------------------------------------------------------------
 * O QUE ELA NUNCA FAZ
 *
 * **Não aprova Tier 3.** Destrutivo é bloqueado, ponto. Aprovação lembrada não
 * é um jeito de subir de nível — se fosse, bastaria uma resposta distraída pra
 * abrir a porta pra sempre.
 *
 * **Não é permanente por padrão.** Toda aprovação tem prazo. Permissão eterna
 * concedida num contexto que já mudou é a origem de metade dos incidentes de
 * privilégio.
 *
 * **Não aprova por semelhança.** A chave é exata: mesmo programa, mesmos
 * argumentos relevantes, mesmo escopo. "Parecido" é onde um aprovador ingênuo
 * deixa passar `rm arquivo.txt` porque `rm arquivo.log` foi aprovado.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { leJsonConfig } from "./json-config.js";

const PRAZO_PADRAO_MS = 60 * 60 * 1000;      // 1 hora
const PRAZO_MAX_MS = 24 * 60 * 60 * 1000;    // teto duro: nada dura mais que um dia
const MAX_REGISTROS = 500;

function arquivo() {
  /* Mesmo caminho do resto do agente (apps.js, atalhos.js, listener.js). Eu
     tinha usado %APPDATA%, que é fora do padrão daqui — e o efeito prático foi
     teste gravando no perfil real do usuário, porque os testes redirecionam
     JARVIS_AGENT_DIR e não o APPDATA. */
  const dir = process.env.JARVIS_AGENT_DIR || path.join(os.homedir(), ".jarvis-agente");
  return path.join(dir, "aprovacoes.json");
}

/**
 * Identidade EXATA da ação. Ver o cabeçalho: aprovar por semelhança é como um
 * aprovador ingênuo deixa passar o comando errado.
 *
 * O escopo entra na chave porque "pode ler nesta pasta" e "pode ler naquela"
 * são autorizações diferentes, ainda que o programa seja o mesmo.
 */
export function chaveDa({ programa, argumentos = [], escopo = "" }) {
  const bruto = JSON.stringify([
    String(programa || "").toLowerCase(),
    (argumentos || []).map((a) => String(a)),
    String(escopo || ""),
  ]);
  return crypto.createHash("sha256").update(bruto).digest("hex").slice(0, 32);
}

function carrega() {
  try {
    const dados = leJsonConfig(arquivo());
    return Array.isArray(dados?.registros) ? dados.registros : [];
  } catch {
    /* Arquivo ausente ou corrompido = nenhuma aprovação lembrada. Falhar
       "fechado" aqui é o único padrão aceitável: um erro de leitura NÃO pode
       virar permissão. */
    return [];
  }
}

function grava(registros) {
  const alvo = arquivo();
  fs.mkdirSync(path.dirname(alvo), { recursive: true });
  /* Sem BOM e em UTF-8 explícito: o PowerShell 5.1 grava BOM por padrão, e um
     BOM no começo já fez `JSON.parse` descartar config inteira neste projeto. */
  fs.writeFileSync(alvo, JSON.stringify({ registros }, null, 1), { encoding: "utf8" });
}

function vivos(registros, agora = Date.now()) {
  return registros.filter((r) => r.expira > agora);
}

/**
 * Esta ação já foi aprovada e a aprovação ainda vale?
 *
 * Devolve `{ aprovado, motivo, restanteMs }`. O motivo existe pra o log poder
 * dizer POR QUE não perguntou — uma ação que roda sozinha sem explicação é
 * indistinguível de um gate quebrado.
 */
export function consulta(acao, agora = Date.now()) {
  if (Number(acao?.tier) >= 3) {
    return { aprovado: false, motivo: "Tier 3 é bloqueado; aprovação não sobe nível" };
  }
  const chave = chaveDa(acao);
  const achado = vivos(carrega(), agora).find((r) => r.chave === chave);
  if (!achado) return { aprovado: false, motivo: "nunca aprovado (ou já expirou)" };
  if (Number(acao?.tier) > Number(achado.tier)) {
    /* A mesma chave com tier MAIOR é outra situação: o que foi aprovado como
       leitura não autoriza a mesma coisa reclassificada como escrita. */
    return { aprovado: false, motivo: `aprovado no tier ${achado.tier}, pedido no ${acao.tier}` };
  }
  return {
    aprovado: true,
    motivo: `aprovado em ${new Date(achado.quando).toLocaleTimeString("pt-BR")}`,
    restanteMs: achado.expira - agora,
  };
}

/**
 * Registra que o Victor disse sim.
 *
 * `prazoMs` é limitado a 24h SEMPRE, mesmo se quem chamou pedir mais. Um teto
 * que quem chama pode ignorar não é teto.
 */
export function registra(acao, { prazoMs = PRAZO_PADRAO_MS, agora = Date.now() } = {}) {
  if (Number(acao?.tier) >= 3) return false;      // ver o cabeçalho
  const prazo = Math.min(Math.max(Number(prazoMs) || 0, 0), PRAZO_MAX_MS);
  if (prazo <= 0) return false;

  const chave = chaveDa(acao);
  const registros = vivos(carrega(), agora).filter((r) => r.chave !== chave);
  registros.push({
    chave, tier: Number(acao?.tier) || 0, quando: agora, expira: agora + prazo,
    /* Descrição legível pro Victor poder auditar e revogar sem decifrar hash. */
    descricao: String(acao?.descricao || acao?.programa || "").slice(0, 120),
  });
  grava(registros.slice(-MAX_REGISTROS));
  return true;
}

/** Tudo que está valendo agora, pra uma tela de "o que eu autorizei". */
export function listar(agora = Date.now()) {
  return vivos(carrega(), agora).map((r) => ({
    descricao: r.descricao,
    tier: r.tier,
    expiraEm: Math.round((r.expira - agora) / 60000) + " min",
  }));
}

/**
 * Revoga. Sem argumento, revoga tudo.
 *
 * Existe porque autorização sem botão de desfazer é autorização que ninguém
 * concede com tranquilidade — e a pessoa acaba dizendo não pra tudo, que é o
 * mesmo problema pelo outro lado.
 */
export function revoga(acao = null, agora = Date.now()) {
  if (!acao) {
    grava([]);
    return true;
  }
  const chave = chaveDa(acao);
  const registros = vivos(carrega(), agora);
  const restantes = registros.filter((r) => r.chave !== chave);
  grava(restantes);
  return restantes.length !== registros.length;
}
