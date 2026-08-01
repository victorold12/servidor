/**
 * Leitura dos arquivos de configuração do agente (`~/.jarvis-agente/*.json`).
 *
 * ---------------------------------------------------------------------------
 * POR QUE ISTO EXISTE: O BOM QUE APAGAVA A CONFIGURAÇÃO INTEIRA
 *
 * O instalador escreve `stt.json` e `listener.json` pelo PowerShell, e o
 * `Set-Content -Encoding UTF8` do PowerShell 5.1 — que é o que o Windows tem —
 * grava UTF-8 **com BOM**. O `JSON.parse` estoura no BOM ("Unexpected token"),
 * e como todo carregador daqui envolve o parse num `catch` que devolve os
 * padrões, o resultado era este:
 *
 *     no disco:  modelsDir = C:\...\Documents\VTz LLM\whisper\modelos
 *     o app lia: modelsDir = C:\...\.jarvis-agente\whisper-models   (padrão)
 *
 * Ou seja: o instalador dizia "[ok] stt.json atualizado", o arquivo ESTAVA lá
 * com o conteúdo certo, e o agente ignorava tudo — procurando o modelo do
 * whisper numa pasta que nunca existiu. Silencioso dos dois lados, e por isso
 * sobreviveu a várias sessões.
 *
 * O `catch` continua certo: config corrompida não pode derrubar o agente. O que
 * faltava era não tratar um arquivo PERFEITAMENTE VÁLIDO como corrompido.
 *
 * Consertar só o instalador não bastaria: qualquer editor de texto do Windows
 * (o Bloco de Notas, inclusive) salva com BOM se a pessoa mexer no arquivo à
 * mão. Quem lê é que tem que ser tolerante.
 */
import fs from "node:fs";

/**
 * Lê um JSON de configuração, tolerando BOM. Devolve `null` quando o arquivo
 * não existe ou não é JSON válido — quem chama decide o padrão.
 */
export function leJsonConfig(caminho) {
  let texto;
  try {
    texto = fs.readFileSync(caminho, "utf8");
  } catch {
    return null;   // não existe ainda: é o estado normal antes do primeiro uso
  }
  try {
    // \uFEFF: o BOM chega como um caractere invisível no início da string.
    return JSON.parse(texto.replace(/^\uFEFF/, ""));
  } catch {
    return null;   // conteúdo inválido de verdade
  }
}
