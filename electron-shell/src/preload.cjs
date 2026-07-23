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

// `process` aqui é o global do Node exposto pelo próprio preload (mesmo sob
// sandbox) — não precisa (e não dá pra) importar do pacote "electron".
contextBridge.exposeInMainWorld("jarvisDesktop", {
  isElectron: true,
  platform: process.platform,
});
