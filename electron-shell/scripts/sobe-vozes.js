#!/usr/bin/env node
/**
 * Sobe os motores de voz e espera a PORTA RESPONDER. Sai 0 se todos os que
 * estão instalados atenderem; 1 se algum não atender.
 *
 * ---------------------------------------------------------------------------
 * POR QUE ISTO EXISTE
 *
 * O CI passou 7/7 testando a *instalação* e nunca ligou os servidores. Validar
 * a etapa errada custou uma madrugada, e o instalador foi entregue duas vezes
 * com a mesma lacuna: `pip` terminando com código 0 não é prova de que dá pra
 * usar. Na primeira execução numa máquina de verdade, os dois motores morreram
 * em segundos — um com o torch corrompido, outro com o ambiente vazio — e nada
 * disso apareceria num teste que só confere se as pastas foram criadas.
 *
 * O critério de pronto deste projeto é o servidor **respondendo na porta**.
 * Este script é esse critério, escrito.
 *
 * ---------------------------------------------------------------------------
 * POR QUE REUSA O MÓDULO DO APP, EM VEZ DE SUBIR OS SERVIDORES POR CONTA
 *
 * Se aqui tivesse um `spawn` próprio, este script provaria que *algum* jeito de
 * ligar o Chatterbox funciona — não que o jeito do JARVIS funciona. Chamando
 * `ligaMotores` e `portaRespondendo`, o que o CI exercita é exatamente o
 * caminho que roda quando a pessoa clica no botão.
 *
 * Uso: node scripts/sobe-vozes.js [segundos]   (padrão 240)
 */
import { ligaMotores, motoresEmDisco, paraMotores, portaRespondendo, raizDasVozes } from "../src/instalador-vozes.js";
import os from "node:os";
import path from "node:path";

/* O Electron dá `app.getPath('documents')`; fora dele, o mais próximo honesto é
   o padrão do Windows. Serve pro CI, onde o perfil é o do runner e nada foi
   movido pro OneDrive. */
const documentos = process.env.JARVIS_DOCUMENTOS || path.join(os.homedir(), "Documents");
const limite = Number(process.argv[2] || 240) * 1000;

/* Só o Chatterbox reprova o teste. O Kokoro é o RESERVA (é assim que o painel o
   descreve: "principal" x "fallback") — quem tem o Chatterbox de pé tem voz
   clonada, que é o que o usuário quer. Deixar o build vermelho por causa do
   reserva esconderia regressão no principal atrás de ruído. */
const OBRIGATORIOS = new Set((process.env.JARVIS_VOZES_OBRIGATORIAS || "chatterbox").split(","));

/* ===========================================================================
 * PORTA ABERTA NÃO É MOTOR PRONTO — e esta é a segunda vez que este projeto
 * aprende a mesma lição num degrau acima.
 *
 * O Chatterbox subiu, atendeu na 8004, e o teste deu "ok". Só que o log dele
 * dizia, três linhas antes:
 *
 *     TypeError: 'NoneType' object is not callable   (perth.PerthImplicitWatermarker)
 *     CRITICAL: TTS Model failed to load on startup.
 *
 * Ou seja: o servidor responde ao painel e não fala. "O comando terminou com
 * código 0" virou "a porta abriu" — mais perto da verdade, ainda não a verdade.
 * O que prova motor pronto é o modelo ter carregado, e isso o próprio servidor
 * grita no stdout. Ler o que ele grita é mais honesto que confiar no socket.
 * =========================================================================== */
const SINAIS_DE_MODELO_MORTO = [
  /TTS Model failed to load/i,
  /Failed to load model/i,
  /object is not callable/i,
  /Traceback \(most recent call last\)/i,
];

/** Linhas que cada motor imprimiu, pra decidir se ele subiu de verdade. */
const ditoPor = new Map();

const log = (s) => console.log(s);

const instalados = motoresEmDisco(documentos).filter((m) => m.instalado);
log(`raiz: ${raizDasVozes(documentos)}`);
for (const m of motoresEmDisco(documentos)) {
  log(`  ${m.nome}: ${m.instalado ? "instalado (" + m.via + ")" : "NÃO instalado — " + m.motivo}`);
}

if (!instalados.length) {
  log("\nNenhum motor instalado. Não há o que ligar.");
  process.exit(1);
}

/* Guarda o que cada motor falou, além de imprimir. O prefixo "[Nome] " é posto
   por ligaMotores, então dá pra atribuir a linha ao motor certo sem inventar
   outro canal. */
const vivos = await ligaMotores({
  documentos,
  aoLinha: (linha) => {
    log(linha);
    for (const m of instalados) {
      if (linha.startsWith(`[${m.nome}]`)) {
        if (!ditoPor.has(m.id)) ditoPor.set(m.id, []);
        ditoPor.get(m.id).push(linha);
      }
    }
  },
});

const modeloMorreu = (id) =>
  (ditoPor.get(id) || []).some((l) => SINAIS_DE_MODELO_MORTO.some((re) => re.test(l)));

/* Espera de verdade: o Chatterbox carrega ~4 GB de modelo antes de abrir a
   porta. Perguntar uma vez e desistir reprovaria uma instalação boa. */
const inicio = Date.now();
const pendentes = new Map(instalados.map((m) => [m.id, m]));
const ok = new Set();

while (pendentes.size && Date.now() - inicio < limite) {
  for (const [id, m] of [...pendentes]) {
    if (await portaRespondendo(m.porta, 1000)) {
      const seg = Math.round((Date.now() - inicio) / 1000);
      log(`[${m.nome}] RESPONDEU na porta ${m.porta} depois de ${seg}s.`);
      ok.add(id);
      pendentes.delete(id);
    }
  }
  /* Um servidor que morreu não vai responder nunca — não vale gastar o resto do
     limite esperando por ele. */
  for (const [id, m] of [...pendentes]) {
    const v = vivos.find((x) => x.id === id);
    if (v && v.filho.exitCode !== null) {
      log(`[${m.nome}] o processo morreu (código ${v.filho.exitCode}) — não vai responder.`);
      pendentes.delete(id);
    }
  }
  if (pendentes.size) await new Promise((r) => setTimeout(r, 3000));
}

log("\n=== veredito ===");
const quebrados = [];
for (const m of instalados) {
  const atendeu = ok.has(m.id);
  const morto = modeloMorreu(m.id);
  const pronto = atendeu && !morto;
  if (!pronto) quebrados.push(m);

  const situacao = !atendeu ? "não respondeu na porta"
    : morto ? "ATENDE A PORTA MAS O MODELO NÃO CARREGOU — responderia ao painel sem falar"
    : "pronto";
  const marca = pronto ? "ok    " : OBRIGATORIOS.has(m.id) ? "FALHOU" : "aviso ";
  log(`  ${marca} ${m.nome} (porta ${m.porta}): ${situacao}`);

  /* Quando quebrou, repetir o que ELE disse vale mais que qualquer diagnóstico
     meu: a causa está no stdout do próprio servidor. */
  if (!pronto) {
    for (const l of (ditoPor.get(m.id) || []).filter((l) => SINAIS_DE_MODELO_MORTO.some((re) => re.test(l)))) {
      log(`         ${l}`);
    }
  }
}

paraMotores(vivos);

const reprova = quebrados.filter((m) => OBRIGATORIOS.has(m.id));
if (!quebrados.length) {
  log("\nTodos os motores instalados subiram e carregaram o modelo.");
} else if (!reprova.length) {
  log(`\nSó motor(es) opcional(is) com problema: ${quebrados.map((m) => m.nome).join(", ")}.`);
  log("O principal está de pé, então isto não reprova o build — mas está registrado acima.");
}
if (reprova.length) log(`\n${reprova.map((m) => m.nome).join(", ")} não ficou(ram) pronto(s). Isto reprova.`);
process.exit(reprova.length ? 1 : 0);
