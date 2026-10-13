"""
ETAPA 5 -- MCP Server do RH (30 min). Volta aqui na ETAPA 9 (token, regra N8 e auditoria).

Os dados saem de dentro do agente e passam a morar num PROCESSO SEPARADO, que fala MCP. O agente (Etapa 5.3) e os
nós do grafo (Etapa 7, via cliente_mcp.chamar_mcp) só enxergam as tools abaixo: nunca os CSVs.

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 5.1 -- as 5 tools de LEITURA: declare cada uma com @mcp.tool(), escreva a DOCSTRING (é o "schema" que o LLM
               lê) e devolva o resultado da consulta pronta de dados_rh.py. Toda tool devolve UM dict.
  ETAPA 5.2 -- a tool de ESCRITA registrar_decisao, IDEMPOTENTE (protocolo repetido não duplica)
  ETAPA 9.2 -- autorização NO SERVER: token + regra N8 (chefia certa, nunca o próprio servidor) + decisão num enum
  ETAPA 9.3 -- auditoria: toda tentativa de escrita (ALLOW ou DENY) vira uma linha em saidas/auditoria.jsonl

REFERÊNCIAS NAS AULAS
  aula6/desafio2/mcp_unidades.py               MCP Server que lê um CSV                          <- o mais parecido (5.1)
  aula5/exemplos/03_mcp_parametros/server.py   tool com parâmetros opcionais
  aula5/exemplos/05_multiplas_tools/server.py  várias tools no mesmo server, tool de "descoberta"
  aula3/agente_retry3.py                       idempotência (5.2)
  aula5/exemplos/10_seguranca/server_seguro.py token, enum fechado e auditoria NO SERVER        <- o mais parecido (9.2/9.3)

Testar sem agente (MCP Inspector, precisa de Node.js):
    npx @modelcontextprotocol/inspector python etapa05_mcp_rh.py

Pronto quando: o Inspector lista as 6 tools; registrar C1 duas vezes gera um único registro.
"""
import json
import os
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from dados_rh import PASTA, SAIDAS, carregar_servidores, diaria, escala_da_equipe, normas, remuneracao, servidor_publico

# O server roda como SUBPROCESSO: ele não herda o ambiente de quem o chamou. Por isso carrega o .env sozinho
# (mesmo cuidado de aula5/exemplos/02_mcp_basico/database.py).
load_dotenv(PASTA / ".env")

mcp = MCPServer("rh-mcp")

ARQUIVO_REGISTROS = SAIDAS / "registros.json"
ARQUIVO_AUDITORIA = SAIDAS / "auditoria.jsonl"
TOKEN_REGISTRO = os.getenv("TOKEN_REGISTRO", "")
DECISOES_VALIDAS = {"deferido", "indeferido", "indeferido_pela_chefia"}
TIPOS_COM_CHEFIA = {"ferias", "diaria"}  # regra N8


def _ler_registros() -> dict:
    """(PRONTO) {protocolo: registro} gravados até agora."""
    if ARQUIVO_REGISTROS.exists():
        return json.loads(ARQUIVO_REGISTROS.read_text(encoding="utf-8"))
    return {}


def _gravar_registros(registros: dict) -> None:
    """(PRONTO)"""
    ARQUIVO_REGISTROS.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ ETAPA 5.1: leitura
@mcp.tool()
def consultar_servidor(matricula: str) -> dict:
    """Consulta o cadastro de UM servidor: nome, cargo, equipe, saldo de férias (dias), abonos restantes e a
    matrícula da chefia imediata. NÃO devolve o salário (para isso existe consultar_remuneracao, restrita).

    Args:
        matricula: matrícula do servidor, 4 dígitos (ex.: "1002").

    Returns:
        dict com o cadastro, ou {"erro": "matrícula não encontrada"}.
    """
    return servidor_publico(matricula)


@mcp.tool()
def consultar_escala(equipe: str, inicio: str, fim: str) -> dict:
    """Consulta a escala de uma equipe (regra N5): quem da equipe já está afastado em algum dia do período e quantos
    podem estar afastados ao mesmo tempo (30% da equipe, arredondado para baixo, mínimo 1).

    Args:
        equipe: nome da equipe, como no cadastro (ex.: "Cartório", "Plantão A").
        inicio: primeiro dia do período, AAAA-MM-DD (ex.: "2027-07-12").
        fim: último dia do período, AAAA-MM-DD (ex.: "2027-07-26").

    Returns:
        dict com equipe, tamanho_equipe, limite_afastados e a lista afastamentos (matrícula, início, fim, tipo)
        que se sobrepõem ao período; ou {"erro": ...} se a equipe não existe.
    """
    return escala_da_equipe(equipe, inicio, fim)


@mcp.tool()
def consultar_normas(tema: str) -> dict:
    """Consulta as regras da Norma Interna de RH (N1 a N10) de um tema.

    Args:
        tema: um destes: "ferias" (N1-N3), "prazos" (N4), "escala" (N5), "abono" (N6), "diaria" (N7),
              "aprovacao" (N8), "saude" (N9) ou "dados" (N10). Acento e maiúscula não importam.

    Returns:
        {"tema": tema, "regras": [{"codigo", "tema", "regra"}, ...]} (lista vazia se o tema não existe).
    """
    # Um dict, e não a lista direto: uma tool MCP que devolve LISTA manda cada item como um conteúdo separado.
    return {"tema": tema, "regras": normas(tema)}


@mcp.tool()
def tabela_diarias(tipo_destino: str) -> dict:
    """Consulta o valor de UMA diária de viagem a serviço (regra N7) para o tipo de destino.

    Args:
        tipo_destino: "capital" (capital brasileira), "interior" (outra cidade do Brasil) ou "exterior".

    Returns:
        {"moeda": "BRL" ou "USD", "valor_diaria": float}, ou {"erro": ...} se o tipo não existe.
        No exterior o valor vem em USD e precisa ser convertido pela cotação do dia.
    """
    return diaria(tipo_destino)


@mcp.tool()
def consultar_remuneracao(matricula: str) -> dict:
    """[RESTRITA] Consulta o salário-base de um servidor. Dado sensível: use SOMENTE para calcular o valor da venda
    de férias (regra N2: dias vendidos x salario_base / 30). Só o especialista Financeiro deve usar esta tool.

    Args:
        matricula: matrícula do servidor, 4 dígitos (ex.: "1002").

    Returns:
        {"matricula": ..., "salario_base": float}, ou {"erro": "matrícula não encontrada"}.
    """
    return remuneracao(matricula)


# ------------------------------------------------------------------ ETAPA 5.2 / 9.2 / 9.3: escrita
def _auditar(protocolo: str, decisao_acesso: str, motivo: str, parametros: dict) -> None:
    # ETAPA 9.3 -- acrescente UMA linha JSON em ARQUIVO_AUDITORIA com: quando (datetime.now().isoformat()),
    #   thread_id, quem pediu (aprovador), tool ("registrar_decisao"), protocolo, decisao_acesso ("ALLOW"/"DENY"),
    #   motivo e os parâmetros (SEM o token e SEM o despacho inteiro).
    #   Referência: aula5/exemplos/10_seguranca/server_seguro.py (_registrar_auditoria), aqui em JSON Lines.
    #   Até fazer a 9.3, este pass deixa a escrita funcionar sem auditoria.
    pass


@mcp.tool()
def registrar_decisao(protocolo: str, matricula: str, tipo: str, inicio: str, fim: str, decisao: str,
                      aprovador: str, despacho: str, token: str, thread_id: str = "") -> dict:
    """[ESCRITA -- requer autorização] Grava a decisão final de um pedido (férias, abono ou diária) no registro do
    RH. É idempotente: se o protocolo já foi gravado, NÃO grava de novo e responde duplicado=True.

    Args:
        protocolo: protocolo idempotente do pedido (etapa04_ferramentas.gerar_protocolo).
        matricula: matrícula do servidor que fez o pedido.
        tipo: "ferias", "abono" ou "diaria".
        inicio: primeiro dia do pedido, AAAA-MM-DD.
        fim: último dia do pedido, AAAA-MM-DD.
        decisao: "deferido", "indeferido" ou "indeferido_pela_chefia".
        aprovador: matrícula de quem aprovou (a chefia imediata, quando a N8 exige) ou "sistema".
        despacho: texto do despacho (sem CPF nem dado de saúde, N10).
        token: token de registro. Sem ele, a gravação é negada.
        thread_id: identificador da execução (para a auditoria).

    Returns:
        {"sucesso": True, "protocolo": ...}, {"sucesso": True, "duplicado": True, ...} ou {"sucesso": False, "erro": ...}.
    """
    parametros = {"matricula": matricula, "tipo": tipo, "inicio": inicio, "fim": fim, "decisao": decisao,
                  "aprovador": aprovador, "thread_id": thread_id}

    # ETAPA 9.2 -- ANTES de gravar, negue (e audite com DENY) quando:
    #   - token != TOKEN_REGISTRO (ou TOKEN_REGISTRO vazio);
    #   - decisao não está em DECISOES_VALIDAS;
    #   - aprovador == matricula (ninguém aprova o próprio pedido, N8);
    #   - decisao == "deferido" e tipo in TIPOS_COM_CHEFIA e aprovador != chefia do servidor no cadastro.
    #   Devolva {"sucesso": False, "erro": "..."} -- quem nega é o SERVER, não o agente.
    #   Referência: aula5/exemplos/10_seguranca/server_seguro.py (alterar_status_ocorrencia)

    # ETAPA 5.2 -- grave em ARQUIVO_REGISTROS (use _ler_registros/_gravar_registros).
    #   Protocolo já existe -> NÃO grave de novo; devolva {"sucesso": True, "duplicado": True, ...}.
    #   Senão grave {**parametros, "despacho": despacho, "registrado_em": ...} e devolva {"sucesso": True, ...}.
    #   Audite com ALLOW (9.3).
    registros = _ler_registros()
    if protocolo in registros:  # idempotência: o mesmo pedido não é gravado duas vezes
        return {"sucesso": True, "duplicado": True, "protocolo": protocolo}
    registros[protocolo] = {**parametros, "despacho": despacho, "registrado_em": datetime.now().isoformat()}
    _gravar_registros(registros)
    return {"sucesso": True, "protocolo": protocolo}


if __name__ == "__main__":
    mcp.run(transport="stdio")
