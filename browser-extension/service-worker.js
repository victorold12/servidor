/* Background da extensão (Manifest V3 — sem página persistente, só eventos).
 * Único papel hoje: abrir o popup via atalho de teclado (Ctrl+Shift+J).
 * Toda a lógica de verdade (busca, extração, preenchimento) mora no popup e
 * no content-script — não há estado de longa duração pra manter aqui.
 */
chrome.commands.onCommand.addListener((command) => {
  if (command === "trigger-assistant") {
    chrome.action.openPopup().catch(() => {
      // openPopup() exige que a janela do navegador esteja em foco; se falhar
      // (ex.: atalho disparado sem foco), não há fallback seguro — o usuário
      // clica no ícone da extensão manualmente.
    });
  }
});
