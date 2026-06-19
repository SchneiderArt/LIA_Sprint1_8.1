from langgraph.graph import StateGraph, START, END

from agent.config import URL_BOLETIM
from agent.decisao import avaliar_publicacao, deve_noticiar
from agent.estado import AgenteState
from agent.llm import get_token_totals
from agent.logger import get_logger
from agent.saida import gerar_rascunho, salvar_rascunho_markdown, salvar_relatorio_csv

logger = get_logger(__name__)


# ── Nós ───────────────────────────────────────────────────────────────────────

def node_avaliar(state: AgenteState) -> dict:
    """
    Camada 2 — Decisão.
    Consome a primeira publicação da fila, avalia o valor jornalístico via LLM
    e devolve a avaliação para o próximo nó decidir o caminho.
    """
    if not state["publicacoes"]:
        raise RuntimeError("node_avaliar chamado com fila vazia — verifique rota_apos_registrar")

    pub = state["publicacoes"][0]
    restantes = state["publicacoes"][1:]

    avaliacao = avaliar_publicacao(
        titulo=pub["titulo_original"],
        texto_ato=pub["texto_ato"],
    )

    return {
        "publicacoes": restantes,
        "publicacao_atual": pub,
        "avaliacao_atual": avaliacao,
        "rascunho_atual": None,
    }


def node_rascunho(state: AgenteState) -> dict:
    """
    Camada 3 — Geração do rascunho.
    Executado somente para publicações aprovadas na Camada 2.
    Gera o texto jornalístico via LLM e valida com Pydantic.
    """
    pub = state["publicacao_atual"]
    avaliacao = state["avaliacao_atual"]

    rascunho = gerar_rascunho(
        titulo=pub["titulo_original"],
        texto_ato=pub["texto_ato"],
        avaliacao=avaliacao,
        link_original=URL_BOLETIM,
    )

    return {"rascunho_atual": rascunho}


def node_registrar(state: AgenteState) -> dict:
    """
    Camada 3 — Persistência.
    Salva o rascunho em Markdown (se houver) e acumula a linha no relatório CSV.
    O reducer de resultados_csv concatena automaticamente.
    """
    pub = state["publicacao_atual"]
    avaliacao = state["avaliacao_atual"]
    rascunho = state["rascunho_atual"]
    idx = state["idx_rascunho"]

    arquivo_rascunho = ""
    novo_idx = idx

    if rascunho and avaliacao:
        novo_idx = idx + 1
        caminho = salvar_rascunho_markdown(
            idx=novo_idx,
            titulo_original=pub["titulo_original"],
            avaliacao=avaliacao,
            rascunho=rascunho,
        )
        arquivo_rascunho = str(caminho)

    if avaliacao:
        linha = {
            "titulo_original": pub["titulo_original"],
            "relevancia": avaliacao.relevancia,
            "publico_alvo": avaliacao.publico_alvo,
            "tipo_cobertura": avaliacao.tipo_cobertura,
            "noticiado": rascunho is not None,
            "arquivo_rascunho": arquivo_rascunho,
            "justificativa": avaliacao.justificativa,
        }
    else:
        linha = {
            "titulo_original": pub["titulo_original"],
            "relevancia": "erro",
            "publico_alvo": "",
            "tipo_cobertura": "erro",
            "noticiado": False,
            "arquivo_rascunho": "",
            "justificativa": "Falha na chamada ao LLM.",
        }

    return {
        "resultados_csv": [linha],
        "idx_rascunho": novo_idx,
    }


def node_finalizar(state: AgenteState) -> dict:
    """
    Nó terminal.
    Persiste o relatório CSV consolidado e imprime o resumo da execução.
    """
    resultados = state["resultados_csv"]
    salvar_relatorio_csv(resultados)

    totais = get_token_totals()
    total = len(resultados)
    noticiados = sum(1 for r in resultados if r["noticiado"])

    logger.info(
        "grafo | finalizado | total=%d noticiados=%d tokens=%d chamadas=%d",
        total, noticiados, totais["total"], totais["calls"],
    )
    print(f"\n=== RESUMO ===")
    print(f"Publicações analisadas : {total}")
    print(f"Matérias geradas       : {noticiados}")
    print(f"Tokens consumidos      : {totais['total']} ({totais['calls']} chamadas)")
    print(f"Rascunhos em           : saidas/rascunhos/")
    print(f"Relatório em           : saidas/relatorio_cobertura.csv")
    print(f"Log em                 : saidas/execucao_agente.log")

    return {}  # correto em LangGraph: sem campos para atualizar no estado


# ── Arestas condicionais ──────────────────────────────────────────────────────

def rota_apos_avaliar(state: AgenteState) -> str:
    """Após avaliar: se deve noticiar vai para rascunho, senão vai direto para registrar."""
    avaliacao = state["avaliacao_atual"]
    if avaliacao and deve_noticiar(avaliacao):
        return "rascunho"
    return "registrar"


def rota_apos_registrar(state: AgenteState) -> str:
    """Após registrar: se ainda há publicações na fila volta para avaliar, senão finaliza."""
    if state["publicacoes"]:
        return "avaliar"
    return "finalizar"


# ── Construção do grafo ───────────────────────────────────────────────────────

def construir_grafo():
    """
    Monta e compila o grafo LangGraph do agente AGECOM.

    Fluxo:
        START
          └─► avaliar ──► (deve noticiar?) ──► rascunho ─┐
                       └─► (não-noticiar) ───────────────┤
                                                         ▼
                                                    registrar
                                                         │
                                          (há mais?) ───┤
                                               ▼        └──► avaliar (loop)
                                          finalizar
                                               │
                                             END
    """
    grafo = StateGraph(AgenteState)

    grafo.add_node("avaliar", node_avaliar)
    grafo.add_node("rascunho", node_rascunho)
    grafo.add_node("registrar", node_registrar)
    grafo.add_node("finalizar", node_finalizar)

    grafo.add_edge(START, "avaliar")

    grafo.add_conditional_edges(
        "avaliar",
        rota_apos_avaliar,
        {"rascunho": "rascunho", "registrar": "registrar"},
    )

    grafo.add_edge("rascunho", "registrar")

    grafo.add_conditional_edges(
        "registrar",
        rota_apos_registrar,
        {"avaliar": "avaliar", "finalizar": "finalizar"},
    )

    grafo.add_edge("finalizar", END)

    return grafo.compile()
