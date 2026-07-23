/**
 * Empacotamento pra .msi — "JARVIS Agente Local" (Seção 10 do prompt mestre):
 * SÓ o Agente Local numa bandeja, sem a Web App embutida. Pra quem já usa o
 * JARVIS pelo navegador (site) e só quer habilitar controle do PC.
 *
 * Honesto sobre "menor" (como o PDF descreve): este pacote não inclui a Web
 * App (webapp/**), então é menor que o completo — mas ainda embute o runtime
 * do Electron/Chromium (não tem como escapar disso usando electron-builder;
 * um instalador de verdade sem Electron exigiria outra cadeia de build —
 * pkg/nexe + WiX direto — não implementado aqui).
 *
 * `main` sobrescrito via extraMetadata pra apontar pro entrypoint headless
 * (main-agent-only.js) sem duplicar o package.json fonte do outro instalador.
 */
export default {
  appId: "com.vtz.jarvis.agentonly",
  productName: "JARVIS Agente Local",
  copyright: "VTz",
  extraMetadata: {
    main: "src/main-agent-only.js",
  },
  directories: {
    output: "dist-agent-only",
    buildResources: "build",
  },
  files: [
    "src/**/*",
    "package.json",
    "!webapp/**/*",
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
    oneClick: false,
    createDesktopShortcut: false,
    createStartMenuShortcut: true,
    runAfterFinish: true,
  },
};
