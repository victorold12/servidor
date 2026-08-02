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
/* PERFIL — a mesma informação lida como "o que dá pra usar hoje", que é a
   pergunta que a pessoa realmente tem. A lista de capacidades acima diz o que
   falta; o perfil diz o que isso significa. */
const { PERFIS, capacidadesDe, diagnostica, perfilAtual } =
  await import(pathToFileURL(path.join(raizAgente, "src", "presets.js")).href);

const atual = await perfilAtual(async (ids) => linhas.filter((l) => ids.includes(l.id)));
console.log("");
console.log(`perfil atual: ${atual ? PERFIS[atual].titulo : "nenhum — falta o básico"}`);

/* E o próximo degrau, com o passo concreto. Dizer só "falta chatterbox" manda a
   pessoa caçar; dizer qual perfil ela ganha e por onde começar, não. */
const ordem = ["texto", "escuta", "voz", "local"];
const proximo = ordem[ordem.indexOf(atual) + 1] || (atual ? null : "texto");
if (proximo) {
  const d = await diagnostica(proximo, async (ids) => linhas.filter((l) => ids.includes(l.id)));
  console.log(`próximo degrau: ${PERFIS[proximo].titulo} (${PERFIS[proximo].tempo})`);
  console.log(`  falta: ${d.faltando.map((c) => c.id).join(", ") || "nada"}`);
  if (d.proximoPasso) console.log(`  comece por: ${d.proximoPasso}`);
}
console.log("");

process.exit(faltam.length ? 1 : 0);
