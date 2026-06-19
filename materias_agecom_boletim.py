import argparse
import os
import re
from pathlib import Path

import pdfplumber
from playwright.sync_api import sync_playwright

from agent.config import URL_BOLETIM
from agent.grafo import construir_grafo
from agent.llm import reset_token_totals
from agent.logger import get_logger

logger = get_logger(__name__)
PASTA_EXTRACTION = Path("extraction")
PASTA_SAIDAS = Path("saidas")

def coletar_publicacoes_boletim(headless=False):
    os.makedirs("pdfs", exist_ok=True)
    os.makedirs("extraction", exist_ok=True)
    publicacoes = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        
        try:
            print("Acessando o Boletim Oficial...")
            page.goto("https://boletimoficial.ufms.br/", wait_until="networkidle")
            
            page.wait_for_selector(".link-publicacao")
            itens = page.locator(".link-publicacao")
            
            quantidade = itens.count()
            print(f"\nForam encontradas {quantidade} publicações nesta edição. Iniciando extração total...\n")
            
            for i in range(quantidade):
                page.wait_for_timeout(1200)

                item_atual = itens.nth(i)
                item_atual.scroll_into_view_if_needed()
                
                titulo = item_atual.inner_text().strip().replace('\n', ' ').replace('\r', '')
                print(f"Coletando ({i+1}/{quantidade}): {titulo[:50]}...")
                
                item_atual.click(force=True)
                page.wait_for_timeout(2000)
                
                modal_visivel = page.locator(".ui-dialog").filter(has=page.locator("visible=true"))
                botao_baixar = modal_visivel.locator("button", has_text=re.compile(r"Baixar", re.IGNORECASE)).first
                
                with page.expect_download() as download_info:
                    botao_baixar.click(force=True)
                
                download = download_info.value
                
                titulo_seguro = re.sub(r'[\\/*?:"<>|]', '_', titulo)
                titulo_seguro = titulo_seguro[:150].strip()
                
                nome_arquivo_pdf = f"{titulo_seguro}.pdf"
                caminho_pdf = os.path.join("pdfs", nome_arquivo_pdf)
                
                contador = 1
                while os.path.exists(caminho_pdf):
                    nome_arquivo_pdf = f"{titulo_seguro}_{contador}.pdf"
                    caminho_pdf = os.path.join("pdfs", nome_arquivo_pdf)
                    contador += 1
                    
                download.save_as(caminho_pdf)
                
                botao_fechar = modal_visivel.locator(".ui-dialog-titlebar-close")
                botao_fechar.click(force=True)
                
                try:
                    modal_visivel.wait_for(state="hidden", timeout=3000)
                except:
                    try:
                        botao_fechar.evaluate("node => node.click()")
                        modal_visivel.wait_for(state="hidden", timeout=3000)
                    except:
                        print(" -> [!] Modal fantasma detectado. Recarregando a página para limpar a tela...")
                        page.reload(wait_until="networkidle")
                        page.wait_for_selector(".link-publicacao")
                
                # ---------------------------------------------------------
                # ALTERAÇÃO: Fatiamento da página para posicionar as tabelas
                # no local exato onde aparecem no texto.
                # ---------------------------------------------------------
                texto_extraido = ""
                try:
                    with pdfplumber.open(caminho_pdf) as pdf:
                        tabela_aberta = False
                        colunas_anteriores = 0
                        
                        for pagina in pdf.pages:
                            # Encontra e ordena as tabelas de cima para baixo
                            tabelas_info = pagina.find_tables(table_settings={"intersection_tolerance": 15})
                            tabelas_info = sorted(tabelas_info, key=lambda t: t.bbox[1])
                            
                            current_top = 0
                            
                            for tab in tabelas_info:
                                # 1. Extrai o texto ACIMA da tabela
                                crop_box = (0, current_top, pagina.width, tab.bbox[1])
                                if crop_box[3] > crop_box[1] + 2: 
                                    try:
                                        texto_pedaco = pagina.crop(crop_box).extract_text()
                                        if texto_pedaco and texto_pedaco.strip():
                                            if tabela_aberta:
                                                texto_extraido += "--- FIM DA TABELA ---\n\n"
                                                tabela_aberta = False
                                            texto_extraido += texto_pedaco + " \n\n"
                                    except:
                                        pass
                                
                                # 2. Extrai os dados da tabela no local correto
                                tabela_dados = tab.extract()
                                if tabela_dados:
                                    colunas_atuais = len(tabela_dados[0])
                                    
                                    if tabela_aberta and colunas_atuais == colunas_anteriores:
                                        # É continuação da tabela da página anterior
                                        for linha in tabela_dados:
                                            linha_limpa = [str(celula).replace('\n', ' ') if celula is not None else "" for celula in linha]
                                            texto_extraido += "| " + " | ".join(linha_limpa) + " |\n"
                                    else:
                                        # É uma tabela nova
                                        if tabela_aberta:
                                            texto_extraido += "--- FIM DA TABELA ---\n\n"
                                        texto_extraido += "--- TABELA IDENTIFICADA ---\n"
                                        for linha in tabela_dados:
                                            linha_limpa = [str(celula).replace('\n', ' ') if celula is not None else "" for celula in linha]
                                            texto_extraido += "| " + " | ".join(linha_limpa) + " |\n"
                                        
                                        tabela_aberta = True
                                        colunas_anteriores = colunas_atuais
                                
                                # Move a "régua" de leitura para debaixo desta tabela
                                current_top = tab.bbox[3]
                            
                            # 3. Extrai o restante do texto ABAIXO da última tabela (ou a página inteira, se não houver tabelas)
                            crop_box = (0, current_top, pagina.width, pagina.height)
                            if crop_box[3] > crop_box[1] + 2:
                                try:
                                    texto_pedaco = pagina.crop(crop_box).extract_text()
                                    if texto_pedaco and texto_pedaco.strip():
                                        if tabela_aberta:
                                            texto_extraido += "--- FIM DA TABELA ---\n\n"
                                            tabela_aberta = False
                                        texto_extraido += texto_pedaco + " \n\n"
                                except:
                                    pass
                                    
                        if tabela_aberta:
                            texto_extraido += "--- FIM DA TABELA ---\n\n"
                            
                except Exception as erro_pdf:
                    texto_extraido = f"[ERRO NA LEITURA DO PDF]: {erro_pdf}"
                
                texto_limpo = texto_extraido.strip()

                nome_arquivo_txt = nome_arquivo_pdf.replace(".pdf", ".txt")
                caminho_txt = os.path.join("extraction", nome_arquivo_txt)
                
                with open(caminho_txt, "w", encoding="utf-8") as f_txt:
                    f_txt.write(f"TÍTULO ORIGINAL: {titulo}\n")
                    f_txt.write(f"ARQUIVO ORIGEM: {caminho_pdf}\n")
                    f_txt.write("-" * 50 + "\n\n")
                    f_txt.write(texto_limpo)
                
                publicacoes.append({
                    "titulo_original": titulo,
                    "caminho_arquivo": caminho_pdf,
                    "texto_ato": texto_limpo
                })
                
        except Exception as e:
            print(f"Erro inesperado na camada de coleta: {e}") 
        finally:
            browser.close()
            
    return publicacoes

# ── Carregamento de extração existente ────────────────────────────────────────

def carregar_extracao_existente() -> list[dict]:
    """Lê os arquivos .txt em extraction/ sem rodar o Playwright."""
    if not PASTA_EXTRACTION.exists():
        raise FileNotFoundError("Pasta extraction/ não encontrada. Execute sem --sem-coleta primeiro.")

    arquivos = sorted(PASTA_EXTRACTION.glob("*.txt"))
    if not arquivos:
        raise FileNotFoundError("Nenhum arquivo .txt encontrado em extraction/.")

    publicacoes = []
    for arq in arquivos:
        conteudo = arq.read_text(encoding="utf-8")
        linhas = conteudo.splitlines()

        titulo = ""
        caminho_pdf = ""
        for linha in linhas[:3]:
            if linha.startswith("TÍTULO ORIGINAL:"):
                titulo = linha.replace("TÍTULO ORIGINAL:", "").strip()
            elif linha.startswith("ARQUIVO ORIGEM:"):
                caminho_pdf = linha.replace("ARQUIVO ORIGEM:", "").strip()

        separador = conteudo.find("-" * 10)
        texto_ato = conteudo[separador:].lstrip("-").strip() if separador != -1 else conteudo

        publicacoes.append({
            "titulo_original": titulo or arq.stem,
            "caminho_arquivo": caminho_pdf or str(arq),
            "texto_ato": texto_ato,
        })

    logger.info("coleta | %d publicações carregadas de extraction/", len(publicacoes))
    return publicacoes


# ── Orquestrador principal ────────────────────────────────────────────────────

def executar(headless: bool, sem_coleta: bool) -> None:
    reset_token_totals()
    PASTA_SAIDAS.mkdir(exist_ok=True)

    # Limpa rascunhos anteriores para garantir idempotência
    pasta_rascunhos = PASTA_SAIDAS / "rascunhos"
    if pasta_rascunhos.exists():
        for arq in pasta_rascunhos.glob("*.md"):
            arq.unlink()
    pasta_rascunhos.mkdir(exist_ok=True)

    # Camada 1 — Coleta
    if sem_coleta:
        logger.info("modo | usando extração existente (--sem-coleta)")
        publicacoes = carregar_extracao_existente()
    else:
        logger.info("modo | coleta completa via Playwright")
        publicacoes = coletar_publicacoes_boletim(headless=headless)

    if not publicacoes:
        logger.error("grafo | nenhuma publicação disponível. Encerrando.")
        return

    # Camadas 2 e 3 — executadas pelo grafo LangGraph
    estado_inicial = {
        "publicacoes": publicacoes,
        "publicacao_atual": None,
        "avaliacao_atual": None,
        "rascunho_atual": None,
        "resultados_csv": [],
        "idx_rascunho": 0,
    }

    grafo = construir_grafo()
    grafo.invoke(estado_inicial)


# ── Entry point ───────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agente AGECOM — Matérias a partir do Boletim Oficial da UFMS"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa o navegador sem interface gráfica (padrão: visível)",
    )
    parser.add_argument(
        "--sem-coleta",
        action="store_true",
        help="Pula a coleta via Playwright e usa os arquivos já extraídos em extraction/",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    executar(headless=args.headless, sem_coleta=args.sem_coleta)