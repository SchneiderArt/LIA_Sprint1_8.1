import csv
import json
import os
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError
from schemas import AvaliacaoJornalistica, RascunhoMateria
from agent.llm import call_llm
from agent.logger import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "rascunho.md"
_SAIDAS_DIR = Path("saidas")


def _carregar_prompt_sistema() -> str:
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt de rascunho não encontrado: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")

_SYSTEM_PROMPT = _carregar_prompt_sistema()


def gerar_rascunho(
    titulo: str,
    texto_ato: str,
    avaliacao: AvaliacaoJornalistica,
    link_original: str = "https://boletimoficial.ufms.br/",
) -> RascunhoMateria | None:
    """
    Camada 3 — Saída (parte 1).
    Gera um rascunho de matéria jornalística via LLM e valida com Pydantic.
    Retorna None se o modelo falhar ou devolver JSON inválido.
    """
    user_prompt = (
        f"TÍTULO DO ATO: {titulo}\n"
        f"AVALIAÇÃO JORNALÍSTICA: relevância={avaliacao.relevancia}, "
        f"público-alvo={avaliacao.publico_alvo}, cobertura={avaliacao.tipo_cobertura}\n"
        f"JUSTIFICATIVA DA AVALIAÇÃO: {avaliacao.justificativa}\n\n"
        f"CONTEÚDO DO ATO:\n{texto_ato[:6000]}\n\n"
        f"URL ORIGINAL: {link_original}"
    )

    logger.info("saida | gerando rascunho: %s", titulo[:60])

    try:
        resposta_texto, tokens = call_llm(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
        )
    except RuntimeError as e:
        logger.error("saida | falha na chamada LLM: %s", e)
        return None

    try:
        dados = json.loads(resposta_texto)
        # Garante que link_original venha da fonte, não do modelo
        dados["link_original"] = link_original
        rascunho = RascunhoMateria(**dados)
        logger.info("saida | rascunho gerado | tokens=%d", tokens)
        return rascunho
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        logger.error("saida | JSON inválido para '%s': %s | raw: %s", titulo[:40], e, resposta_texto[:200])
        return None


def _slug(texto: str, max_len: int = 50) -> str:
    import re
    s = re.sub(r"[^\w\s-]", "", texto.lower())
    s = re.sub(r"[\s_-]+", "_", s).strip("_")
    return s[:max_len]


def salvar_rascunho_markdown(
    idx: int,
    titulo_original: str,
    avaliacao: AvaliacaoJornalistica,
    rascunho: RascunhoMateria,
) -> Path:
    """Salva o rascunho como arquivo Markdown em saidas/rascunhos/."""
    pasta = _SAIDAS_DIR / "rascunhos"
    pasta.mkdir(parents=True, exist_ok=True)

    nome_arquivo = f"{idx:03d}_{_slug(rascunho.titulo)}.md"
    caminho = pasta / nome_arquivo

    palavras_chave_str = ", ".join(rascunho.palavras_chave)
    fonte = rascunho.sugestao_fonte or "_Não identificada_"

    conteudo = f"""# {rascunho.titulo}

**Lead:** {rascunho.linha_fina}

---

{rascunho.corpo}

---

**Palavras-chave:** {palavras_chave_str}
**Sugestão de fonte:** {fonte}
**Link original:** {rascunho.link_original}

---
*Ato original:* {titulo_original}
*Avaliação:* relevância={avaliacao.relevancia} | público={avaliacao.publico_alvo} | cobertura={avaliacao.tipo_cobertura}
*Gerado automaticamente — revisar antes de publicar.*
"""
    caminho.write_text(conteudo, encoding="utf-8")
    logger.info("saida | rascunho salvo: %s", caminho)
    return caminho


def salvar_relatorio_csv(resultados: list[dict]) -> Path:
    """
    Salva relatório consolidado em saidas/relatorio_cobertura.csv.
    Cada entrada de resultados deve ter as chaves:
    titulo_original, relevancia, publico_alvo, tipo_cobertura,
    justificativa, noticiado, arquivo_rascunho.
    Idempotente: sobrescreve o arquivo a cada execução.
    """
    _SAIDAS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = _SAIDAS_DIR / "relatorio_cobertura.csv"

    campos = [
        "titulo_original", "relevancia", "publico_alvo",
        "tipo_cobertura", "noticiado", "arquivo_rascunho", "justificativa",
    ]

    with caminho.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for linha in resultados:
            writer.writerow({k: linha.get(k, "") for k in campos})

    logger.info("saida | relatório CSV salvo: %s (%d linhas)", caminho, len(resultados))
    return caminho
