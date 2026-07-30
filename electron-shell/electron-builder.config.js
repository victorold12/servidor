/**
 * Empacotamento pra .msi — "JARVIS Completo" (Seção 10 do prompt mestre):
 * casca Electron + Agente Local + Web App numa janela, bandeja, splash.
 *
 * agente-local E webapp vão como extraResources (fora do app.asar), não
 * misturados no `files` do próprio pacote. Dois motivos:
 *   1. agente-local é um repo IRMÃO, não faz parte do código-fonte deste, e
 *      tem módulo nativo (keytar) — dentro de um asar o Node não carrega o
 *      .node direto, precisaria de unpacking especial.
 *   2. webapp: `files` (com asar:true, o padrão) empacota dentro de
 *      resources/app.asar/webapp/..., mas main.js resolve o caminho como
 *      resources/webapp/... (mesmo padrão do agente-local) — bug real, achado
 *      testando o .msi de verdade no Windows: ERR_FILE_NOT_FOUND procurando
 *      resources/webapp/index.html (existia, só que dentro do asar, em outro
 *      caminho). extraResources bate exatamente com o que webappPath() espera.
 *
 * IMPORTANTE: antes de buildar, o keytar em agente-local/node_modules precisa
 * estar compilado contra o ABI do Electron (não do Node do sistema) — é isso
 * que `npm run dist:win` faz (electron-rebuild), não pule esse passo.
 */
export default {
  appId: "com.vtz.jarvis",
  productName: "JARVIS",
  copyright: "VTz",
  directories: {
    output: "dist",
    buildResources: "build",
  },
  files: [
    "src/**/*",
    "package.json",
  ],
  extraResources: [
    { from: "../agente-local/src", to: "agente-local/src" },
    { from: "../agente-local/node_modules", to: "agente-local/node_modules" },
    { from: "../agente-local/package.json", to: "agente-local/package.json" },
    { from: "webapp", to: "webapp" },
  ],
  win: {
    target: [{ target: "msi", arch: ["x64"] }],
    icon: "build/icon.ico",
  },
  msi: {
    // allowToChangeInstallationDirectory é opção do NSIS, não existe em
    // MsiOptions (o WiX/MSI trata isso diferente) — conferido contra
    // node_modules/app-builder-lib/out/options/{Msi,CommonWindowsInstaller}Options.d.ts,
    // não só copiado do rascunho do doc.
    oneClick: false,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    runAfterFinish: true,
  },
  // Sem target "nsis" declarado em win.target -> só gera o .msi, não os dois.
};
