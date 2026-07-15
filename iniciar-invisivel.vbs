' ============================================================
'  VTz LLM Backend - inicia SEM abrir janela (silencioso)
'  Use DEPOIS de ter rodado o run.bat pelo menos uma vez
'  (a 1a vez instala tudo e mostra erros; esta some com a janela).
'  Dica: coloque um atalho deste arquivo na pasta Inicializar
'  (tecla Win+R -> shell:startup) pra ligar sozinho no boot.
' ============================================================
Set fso = CreateObject("Scripting.FileSystemObject")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = pasta
' roda o run-silencioso.bat com janela oculta (0) e sem esperar (False)
sh.Run "cmd /c """ & pasta & "\run-silencioso.bat""", 0, False
