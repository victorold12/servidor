/**
 * Preload da janela principal. CommonJS de propósito — preload sandboxed do
 * Electron precisa disso independente do "type":"module" do package.json.
 *
 * Capability allowlist explícita e nomeada (Seção 13.1 do esquema — padrão
 * absorvido do Tauri): a Web App só enxerga exatamente o que é exposto aqui,
 * nada de nodeIntegration nem acesso livre a módulos do Node. Hoje só expõe
 * um sinalizador — é o ponto de extensão pronto pra quando a Web App quiser
 * se adaptar ao rodar dentro do shell (ex.: esconder algo que só faz sentido
 * no navegador). Adicionar uma capability = adicionar uma linha aqui, nomeada.
 */
const { contextBridge } = require("electron");

// URL do backend pareado, injetada pelo main.js via webPreferences.
// additionalArguments (process.argv funciona mesmo no preload sandboxed).
// Sem isto, o painel web dentro do Electron não sabia qual backend usar — só
// tentava localhost:8000 — e a aba "Agente Local" ficava vazia mesmo com o
// agente pareado e conectado (bug real, achado testando o .msi no Windows).
function argValue(prefix) {
  const hit = process.argv.find((a) => a.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : null;
}

// `process` aqui é o global do Node exposto pelo próprio preload (mesmo sob
// sandbox) — não precisa (e não dá pra) importar do pacote "electron".
contextBridge.exposeInMainWorld("jarvisDesktop", {
  isElectron: true,
  platform: process.platform,
  backendUrl: argValue("--jarvis-backend-url="),
});
