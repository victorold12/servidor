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

const HERE = path.dirname(new URL(import.meta.url).pathname);
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

console.log(`Web App copiada de ${SOURCE} -> ${DEST} (${FILES.join(", ")})`);
