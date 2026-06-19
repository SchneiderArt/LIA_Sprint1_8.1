import json
import os
from pathlib import Path
from pydantic import ValidationError
from schemas import AvaliacaoJornalistica
from agent.llm import call_llm
from agent.logger import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "avaliacao.md"

def _carregar_prompt_sistema() -> str:
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt de avaliação não encontrado: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")

_SYSTEM_PROMPT = _carregar_prompt_sistema()


def avaliar_publicacao(titulo: str, texto_ato: str) -> AvaliacaoJornalistica | None:
    """
    Camada 2 — Decisão.
    Envia o texto do ato ao LLM e retorna uma AvaliacaoJornalistica validada.
    Retorna None se o modelo falhar ou devolver JSON inválido após retentativas.
    """
    user_prompt = f"TÍTULO DO ATO: {titulo}\n\nCONTEÚDO DO ATO:\n{texto_ato[:6000]}"

    logger.info("decisao | avaliando: %s", titulo[:60])

    try:
        resposta_texto, tokens = call_llm(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
        )
    except RuntimeError as e:
        logger.error("decisao | falha na chamada LLM: %s", e)
        return None

    try:
        dados = json.loads(resposta_texto)
        avaliacao = AvaliacaoJornalistica(**dados)
        logger.info(
            "decisao | resultado: relevancia=%s cobertura=%s tokens=%d",
            avaliacao.relevancia, avaliacao.tipo_cobertura, tokens,
        )
        return avaliacao
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        logger.error("decisao | JSON inválido para '%s': %s | raw: %s", titulo[:40], e, resposta_texto[:200])
        return None


def deve_noticiar(avaliacao: AvaliacaoJornalistica) -> bool:
    """Retorna True se o ato deve virar matéria (tipo_cobertura != 'não-noticiar')."""
    return avaliacao.tipo_cobertura.lower() != "não-noticiar"
