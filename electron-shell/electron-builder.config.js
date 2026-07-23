/**
 * Empacotamento pra .msi — "JARVIS Completo" (Seção 10 do prompt mestre):
 * casca Electron + Agente Local + Web App numa janela, bandeja, splash.
 *
 * agente-local vai como extraResources (fora do app.asar), não misturado no
 * `files` do próprio pacote — ele é um repo IRMÃO, não faz parte do código-
 * fonte deste. Isso também evita o problema comum de módulo nativo (keytar)
 * dentro de um asar: como extraResources fica como arquivo solto em
 * resources/, o Node consegue carregar o .node direto, sem precisar de
 * unpacking especial.
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
    "webapp/**/*",
    "package.json",
  ],
  extraResources: [
    { from: "../agente-local/src", to: "agente-local/src" },
    { from: "../agente-local/node_modules", to: "agente-local/node_modules" },
    { from: "../agente-local/package.json", to: "agente-local/package.json" },
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
