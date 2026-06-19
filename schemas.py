from pydantic import BaseModel, Field
from typing import Optional, List

class AvaliacaoJornalistica(BaseModel):
    relevancia: str = Field(..., description="Deve ser classificada como: alta, média ou baixa")
    publico_alvo: str = Field(..., description="Deve ser: estudantes, servidores, comunidade externa ou pesquisadores")
    tipo_cobertura: str = Field(..., description="Deve ser: nota curta, matéria média, matéria longa ou não-noticiar")
    justificativa: str = Field(..., description="Justificativa livre para as decisões acima")

class RascunhoMateria(BaseModel):
    titulo: str = Field(..., description="Título sugerido para a matéria")
    linha_fina: str = Field(..., description="Linha-fina (lead) do texto")
    corpo: str = Field(..., description="Corpo do texto contendo entre 200 a 400 palavras")
    palavras_chave: List[str] = Field(..., description="Lista de palavras-chave sugeridas")
    sugestao_fonte: Optional[str] = Field(None, description="Sugestão de fonte para entrevistar, se aplicável")
    link_original: str = Field(..., description="URL da publicação original no Boletim Oficial")