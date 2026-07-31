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

const vivos = await ligaMotores({ documentos, aoLinha: log });

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
for (const m of instalados) {
  log(`  ${ok.has(m.id) ? "ok    " : "FALHOU"} ${m.nome} (porta ${m.porta})`);
}

paraMotores(vivos);
const falhou = instalados.length - ok.size;
log(falhou ? `\n${falhou} motor(es) não responderam.` : "\nTodos os motores instalados responderam.");
process.exit(falhou ? 1 : 0);
