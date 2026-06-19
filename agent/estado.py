import operator
from typing import Annotated
from typing_extensions import TypedDict
from schemas import AvaliacaoJornalistica, RascunhoMateria


class AgenteState(TypedDict):
    # Fila de publicações ainda não processadas.
    # Cada nó de avaliação consome a primeira e devolve o restante.
    publicacoes: list[dict]

    # Publicação sendo processada no ciclo atual do grafo.
    publicacao_atual: dict | None

    # Resultado da Camada 2 para a publicação atual.
    avaliacao_atual: AvaliacaoJornalistica | None

    # Resultado da Camada 3 para a publicação atual (None se não-noticiar).
    rascunho_atual: RascunhoMateria | None

    # Lista acumulada de resultados para o CSV.
    # O reducer operator.add concatena automaticamente: cada nó
    # devolve [nova_linha] e o LangGraph acrescenta à lista existente.
    resultados_csv: Annotated[list[dict], operator.add]

    # Contador de rascunhos gerados (usado para nomear os arquivos .md).
    idx_rascunho: int
