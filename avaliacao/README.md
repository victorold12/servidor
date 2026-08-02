# Arnês de avaliação

Mede se o VTz OS **piorou**. Não é teste unitário: o teste afirma propriedades
("a pontuação sobe"), o arnês afirma resultados ("esta pergunta vai pro modelo
certo"). A diferença não é acadêmica — o primeiro caso deste arnês pegou um
defeito que o teste unitário via e aprovava.

## Rodar

```bash
python avaliacao/executa.py                 # tudo, de graça (modelo local)
python avaliacao/executa.py --alvo fala     # só um alvo
python avaliacao/executa.py --etiqueta portugues
python avaliacao/executa.py --verboso       # mostra também o que passou
```

Custa **US$ 0,00** por padrão. Dois dos três alvos não chamam modelo nenhum, e o
terceiro vai pro Ollama desta máquina. A nuvem é opt-in:

```bash
python avaliacao/executa.py --engine openrouter --modelo openai/gpt-4.1-mini
```

Ele avisa antes de gastar.

## Comparar

```bash
python avaliacao/executa.py --nome antes
# ... mexe no código ...
python avaliacao/executa.py --nome depois
python avaliacao/compara.py antes depois
```

`ultima` e `penultima` funcionam como nomes. Sai com código 1 **só** se houver
regressão — melhoria não compensa quebra.

## Os três alvos

| alvo | o que exercita | custa | determinístico |
|---|---|---|---|
| `roteamento` | `app/complexidade.py` decide o motor | não | sim |
| `fala` | `agente-local/src/fala-natural.js` (roda em Node de verdade) | não | sim |
| `resposta` | o modelo respondendo, via `app/openrouter.py` | local: não | quase |

`resposta` roda com `temperature: 0`. Sem isso, duas execuções da mesma versão
do código davam vereditos diferentes — e regressão falsa mata a confiança no
relatório, que é como um arnês morre.

## Acrescentar um caso

Uma linha no `.jsonl` da pasta `casos/`:

```json
{"id": "algo-unico", "alvo": "fala", "entrada": "Isso é **importante**",
 "criterios": [{"tipo": "sem_marcacao"}], "etiquetas": ["markdown"]}
```

O carregador recusa caso sem critério, id repetido e alvo desconhecido — os três
jeitos de um caso inflar o placar sem medir nada.

## Critérios disponíveis

`contem` · `nao_contem` · `regex` · `nao_vazio` · `sem_marcacao` · `engine` ·
`desempatar` · `ate_ms` · `ate_usd` · `juiz`

Um critério com tipo desconhecido vira **indefinido**, nunca aprovação: um typo
no `.jsonl` virando verde seria o pior modo de falha possível.

## A regra que atravessa tudo

**"Não sei julgar" nunca é "passou".** Três resultados, não dois. Um arnês que
devolve verde quando não conseguiu olhar produz a mentira mais cara que existe:
a confiança de que nada quebrou.
