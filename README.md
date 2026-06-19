# 8.1 AGECOM — Produção de Matérias a partir do Boletim Oficial

**Sprint 1 | Squad 2 | Dupla A**
Emily Flores (Emily-Flo223) + Arthur Schneider (SchneiderArt)

Agente assistivo que acessa o Boletim Oficial da UFMS, avalia o valor jornalístico de cada ato publicado via LLM e gera rascunhos de matéria prontos para revisão humana pela equipe da AGECOM.

---

## O que o agente faz

```
Camada 1 — Coleta  (materias_agecom_boletim.py)
  Playwright acessa boletimoficial.ufms.br
  → baixa PDFs de cada ato
  → extrai texto e tabelas com pdfplumber
  → salva em extraction/

Camadas 2 e 3 — Grafo LangGraph  (agent/grafo.py)
  Para cada publicação, o grafo percorre os nós:

  [avaliar] → avalia valor jornalístico via LLM (Camada 2)
            ↓ deve noticiar?
  [rascunho] → gera rascunho de matéria via LLM (Camada 3)
            ↓
  [registrar] → salva .md e acumula resultado no CSV
            ↓ há mais publicações?
  [finalizar] → persiste relatorio_cobertura.csv e imprime resumo
```

Nada vai ao ar sem revisão humana. O agente é assistivo, não autônomo na publicação.

---

## Arquitetura do grafo

```
     START
       │
   [avaliar]  ←────────────────────┐
       │                           │
  deve noticiar?                   │
   sim │   não                     │
       ▼     ▼                     │
 [rascunho]  │                     │
       │     │                     │
       └──►[registrar]             │
               │                  │
          há mais?  ──── sim ──────┘
               │
              não
               ▼
         [finalizar]
               │
              END
```

---

## Módulos do projeto

```
materias_agecom_boletim.py   # entry point: Camada 1 + invoca o grafo
schemas.py                   # modelos Pydantic (AvaliacaoJornalistica, RascunhoMateria)
requirements.txt
.env                         # chave OpenRouter (não versionar)
README.md

agent/
  config.py      # carrega .env → expõe OPENROUTER_API_KEY, LLM_MODEL e URL_BOLETIM
  logger.py      # logging duplo: console + JSON com exec_id único por execução
  llm.py         # única porta para o LLM: retry, contagem de tokens, sanitização
  decisao.py     # lógica da Camada 2: avalia e decide se deve noticiar
  saida.py       # lógica da Camada 3: gera rascunho .md e relatório CSV
  estado.py      # AgenteState — TypedDict compartilhado entre os nós do grafo
  grafo.py       # grafo LangGraph: nós, arestas condicionais e compilação

prompts/
  avaliacao.md   # prompt de sistema para o nó [avaliar]
  rascunho.md    # prompt de sistema para o nó [rascunho]

exemplos/        # 7 atos reais para testes sem coleta

extraction/      # textos extraídos dos PDFs (gerado pela Camada 1)
pdfs/            # PDFs baixados do Boletim Oficial (gerado pela Camada 1)

saidas/
  rascunhos/               # um .md por matéria aprovada
  relatorio_cobertura.csv  # todas as publicações avaliadas
  execucao_agente.log      # log estruturado JSON de cada execução
```

---

## Pré-requisitos

```bash
pip install -r requirements.txt
playwright install chromium
```

Crie um arquivo `.env` na raiz com:

```
OPENROUTER_API_KEY=sua_chave_aqui
LLM_MODEL=google/gemma-4-31b-it
```

---

## Como executar

### Execução completa (coleta + grafo)
```bash
python materias_agecom_boletim.py
```

### Execução com navegador invisível
```bash
python materias_agecom_boletim.py --headless
```

### Usando extração já existente (pula Playwright, roda só o grafo)
```bash
python materias_agecom_boletim.py --sem-coleta
```

---

## Saídas geradas

### `saidas/rascunhos/*.md`
Um arquivo por matéria aprovada: título, lead, corpo (200-400 palavras), palavras-chave, sugestão de fonte e link original.

### `saidas/relatorio_cobertura.csv`
Colunas: `titulo_original`, `relevancia`, `publico_alvo`, `tipo_cobertura`, `noticiado`, `arquivo_rascunho`, `justificativa`

### `saidas/execucao_agente.log`
Log JSON estruturado com `exec_id` único por execução, timestamps e tokens por chamada.

---

## Padrões técnicos

- Rate limiting: 1,2 s entre requisições ao Boletim Oficial
- Sem `sleep` fixo no Playwright — usa `page.wait_for_timeout()` e `wait_for_selector()`
- Saída idempotente: CSV sobrescrito; pasta `rascunhos/` limpa no início de cada execução
- Dados sintéticos nos exemplos — nenhum dado pessoal coletado
- Apenas portais públicos — sem autenticação

---

## Limitações conhecidas

- O seletor `.link-publicacao` do Boletim Oficial pode mudar sem aviso — o script falha com mensagem clara.
- PDFs com texto em imagem (scan) não são legíveis pelo pdfplumber e são registrados com erro no log.
- O modelo LLM pode devolver JSON malformado; nesses casos o ato é ignorado e o erro é logado.
- O agente não acessa edições anteriores do Boletim — somente a edição disponível na página principal.
