#!/usr/bin/env node
/**
 * `doctor` — um comando que diz o estado de tudo.
 *
 * Existe porque investigar um problema neste projeto custava mais em COLETAR
 * estado do que em interpretá-lo. Descobrir por que a voz não falava exigiu
 * diagnósticos separados de venv, torch, perth, uvicorn, ffmpeg e whisper — e
 * cada um respondia uma peça.
 *
 * A regra herdada de `capacidades.js`: cada checagem EXERCITA O CAMINHO, nunca
 * confere presença. Um doctor que reporta "ok" pra coisa quebrada é pior que
 * não ter doctor — ele muda o comportamento de quem confia nele.
 *
 * Sai com código 1 se faltar alguma capacidade NÃO opcional, pra poder ser
 * usado em automação.
 */
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const raizAgente = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "agente-local");
const { verificaTudo } = await import(pathToFileURL(path.join(raizAgente, "src", "capacidades.js")).href);

const linhas = await verificaTudo();

console.log("\n=== JARVIS — o que este PC consegue fazer ===\n");

for (const c of linhas) {
  const marca = c.ok ? "  ok  " : c.opcional ? " aviso" : " FALTA";
  console.log(`${marca}  ${c.id.padEnd(11)} ${c.destrava}`);
  if (c.ok && c.detalhe) console.log(`          ${c.detalhe}`);
  if (!c.ok) {
    console.log(`          motivo: ${c.motivo}`);
    console.log(`          resolver: ${c.resolver}`);
  }
}

const faltam = linhas.filter((c) => !c.ok && !c.opcional);
const avisos = linhas.filter((c) => !c.ok && c.opcional);

console.log("");
if (!faltam.length && !avisos.length) {
  console.log("Tudo no lugar.");
} else {
  if (faltam.length) console.log(`Faltando: ${faltam.map((c) => c.id).join(", ")}`);
  if (avisos.length) console.log(`Opcionais ausentes: ${avisos.map((c) => c.id).join(", ")}`);
}
console.log("");

process.exit(faltam.length ? 1 : 0);
