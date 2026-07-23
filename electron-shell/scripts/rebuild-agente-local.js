#!/usr/bin/env node
/**
 * Recompila dependências nativas do agente-local (hoje: keytar) pro ABI do
 * Electron instalado aqui — sem isso, o keytar empacotado foi buildado pro
 * Node do sistema e não carrega dentro do Electron em runtime.
 *
 * Script Node puro, chamando a API do @electron/rebuild diretamente — não
 * `$(node -p ...)` no package.json (sintaxe de substituição de comando
 * bash/POSIX). O shell padrão do npm no Windows é cmd.exe, que não entende
 * `$(...)`: passava a string literal "$(node" pro --version e quebrava com
 * "Invalid Version" — achado rodando no CI Windows real. Nem CLI: usar a API
 * JS evita shell por completo, em qualquer SO.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { rebuild } from "@electron/rebuild";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const electronVersion = require("electron/package.json").version;
const agenteLocalDir = path.resolve(HERE, "..", "..", "agente-local");

console.log(`Recompilando keytar em ${agenteLocalDir} pro Electron ${electronVersion}...`);

await rebuild({
  buildPath: agenteLocalDir,
  electronVersion,
  onlyModules: ["keytar"],
  force: true,
});

console.log("Rebuild concluído.");
