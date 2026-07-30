#!/usr/bin/env node
/**
 * Copia o build da Web App (repo VTz-painel) pra dentro de electron-shell/webapp,
 * pra o Electron carregar como arquivo local (funciona offline, sem servidor
 * estático). Roda antes de `start` e `dist:win`.
 *
 * Espera VTz-painel como pasta irmã de `servidor` (mesmo padrão de quem clonou
 * os dois repos lado a lado — README explica). Se não achar, erro claro em vez
 * de empacotar um app quebrado silenciosamente.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// fileURLToPath, não new URL(...).pathname: no Windows o pathname de uma URL
// de arquivo vem como "/D:/a/..." (barra antes da letra de unidade) — path.dirname
// nisso produz um caminho inválido tipo "D:\D:\a\..." quando resolvido depois.
// Já era feito certo em src/main.js; faltava aqui (achado rodando no CI Windows real).
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHELL_ROOT = path.resolve(HERE, "..");
const DEST = path.join(SHELL_ROOT, "webapp");

const CANDIDATES = [
  path.resolve(SHELL_ROOT, "..", "..", "VTz-painel"), // servidor/electron-shell -> irmã de servidor
  process.env.JARVIS_WEBAPP_PATH || "",
].filter(Boolean);

const SOURCE = CANDIDATES.find((p) => fs.existsSync(path.join(p, "index.html")));

if (!SOURCE) {
  console.error(
    "Não achei o repo VTz-painel (procurei em: " + CANDIDATES.join(", ") + ").\n" +
      "Clone os dois repos lado a lado:\n" +
      "  git clone https://github.com/victorold12/servidor.git\n" +
      "  git clone https://github.com/victorold12/VTz-painel.git\n" +
      "Ou aponte manualmente: JARVIS_WEBAPP_PATH=/caminho/pro/VTz-painel npm run prepare-webapp"
  );
  process.exit(1);
}

if (!fs.existsSync(path.join(SOURCE, "app.js"))) {
  console.error(`Achei ${SOURCE}, mas falta app.js — rode "npm run build" lá dentro primeiro (build do esbuild).`);
  process.exit(1);
}

fs.rmSync(DEST, { recursive: true, force: true });
fs.mkdirSync(DEST, { recursive: true });

const FILES = ["index.html", "app.js", "style.css"];
for (const f of FILES) {
  const src = path.join(SOURCE, f);
  if (!fs.existsSync(src)) {
    console.error(`Arquivo esperado ausente: ${src}`);
    process.exit(1);
  }
  fs.copyFileSync(src, path.join(DEST, f));
}

/* vendor/ = marked, DOMPurify, xlsx, jspdf, docx, pptxgenjs, html2canvas.
   Desde que sairam do cdnjs, sao arquivos LOCAIS: sem eles o app instalado abre
   com a interface montada e sem markdown nem exportacao — uma falha que so
   aparece quando o usuario tenta usar, o pior momento pra descobrir. Por isso
   aborta aqui em vez de empacotar um app pela metade. */
const VENDOR_SRC = path.join(SOURCE, "vendor");
if (!fs.existsSync(VENDOR_SRC) || fs.readdirSync(VENDOR_SRC).length === 0) {
  console.error(
    `Falta ${VENDOR_SRC}. Rode "npm install && npm run build" no VTz-painel — ` +
    `o build e quem copia as bibliotecas do node_modules pra vendor/.`);
  process.exit(1);
}
fs.cpSync(VENDOR_SRC, path.join(DEST, "vendor"), { recursive: true });
const nVendor = fs.readdirSync(VENDOR_SRC).length;

/* manifest + icones: no Electron nao servem pra instalar nada (o app JA e o
   programa instalado) — sao copiados so pra o <link rel="manifest"> e o
   apple-touch-icon do index.html nao virarem 404 no console.
   sw.js de proposito NAO vem: service worker nao existe em file://.
   Ausencia aqui e aviso, nao erro: o app funciona inteiro sem eles. */
const OPCIONAIS = ["manifest.webmanifest", "icons"];
const copiados = [];
for (const nome of OPCIONAIS) {
  const src = path.join(SOURCE, nome);
  if (!fs.existsSync(src)) continue;
  fs.cpSync(src, path.join(DEST, nome), { recursive: true });
  copiados.push(nome);
}
if (copiados.length < OPCIONAIS.length) {
  console.warn(`Aviso: nao achei ${OPCIONAIS.filter((n) => !copiados.includes(n)).join(", ")} no painel (segue sem).`);
}

console.log(`Web App copiada de ${SOURCE} -> ${DEST} (${FILES.join(", ")} + vendor/ com ${nVendor} libs${copiados.length ? " + " + copiados.join(", ") : ""})`);
