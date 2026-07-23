#!/usr/bin/env node
/** Remove o serviço instalado por install-windows-service.js. Exige Administrador. */
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import pkg from "node-windows";

const { Service } = pkg;

if (os.platform() !== "win32") {
  console.error("Não há serviço do Windows pra remover neste SO.");
  process.exit(1);
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(HERE, "..", "src", "index.js");

const svc = new Service({ name: "JARVIS Agente Local", script: SCRIPT });

svc.on("uninstall", () => console.log('Serviço "JARVIS Agente Local" removido.'));
svc.on("error", (err) => {
  console.error("Falha ao remover o serviço:", err?.message || err);
  process.exitCode = 1;
});

svc.uninstall();
