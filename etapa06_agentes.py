"""
ETAPA 6 -- Os especialistas, cada um com UMA responsabilidade e SÓ as tools de que precisa.

ESQUELETO:
  ETAPA 6.1 -- criar_normas(), criar_escala(), criar_financeiro(), criar_redator()
  ETAPA 6.2 -- criar_coordenador(): usa Normas, Escala e Financeiro como TOOLS (as_tool)

As tools abaixo (PRONTAS) só repassam a chamada ao MCP Server do RH (cliente_mcp.chamar_mcp_async). Dar a cada agente
só as tools dele é o PRIVILÉGIO MÍNIMO (Etapa 9.1); o hook do 🆕 B (etapa10_governanca.py) confere isso em tempo de execução.

REFERÊNCIAS NAS AULAS
  aula4/ex03_agente_as_tool.py                         Coordenador que chama especialistas como tools    <- o mais parecido
  aula2/agente_handoff2.py                             as_tool com tool_name e tool_description
  aula4/ex02_handoff_roteamento.py                     handoff: compare (quem responde no fim?)
  aula7/exemplos/02_agentes_especializados/main.py     uma responsabilidade por agente
  aula7/agentes.py                                     ModelSettings(temperature=0) para respostas mais estáveis
  aula8/exemplos/06_excessive_agency/1_codigo_pronto/main.py   o problema de dar tools DEMAIS a um agente
"""
import json
import os

from agents import Agent, ModelSettings, RunHooks, function_tool

from etapa05_cliente_mcp import chamar_mcp_async
from etapa04_ferramentas import cotacao_usd_brl

# temperature=0 deixa as respostas mais estáveis, mas modelos de raciocínio (gpt-5.x, gpt-6.x, o1/o3...) não aceitam o
# parâmetro (erro 400 "Unsupported parameter: 'temperature'"). Com eles, usamos o padrão do modelo.
_MODELO = os.getenv("OPENAI_DEFAULT_MODEL", "")
CONFIG = ModelSettings() if _MODELO.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")) else ModelSettings(temperature=0)


# ------------------------------------------------------------------ tools (PRONTAS)
@function_tool
async def consultar_normas(tema: str) -> str:
    """Regras da norma interna sobre um tema: férias, prazos, escala, abono, diária, aprovação, saúde ou dados."""
    return json.dumps(await chamar_mcp_async("consultar_normas", {"tema": tema}), ensure_ascii=False)


@function_tool
async def consultar_escala(equipe: str, inicio: str, fim: str) -> str:
    """Afastamentos da equipe que se sobrepõem ao período (AAAA-MM-DD) e o limite de afastados da regra N5."""
    return json.dumps(await chamar_mcp_async("consultar_escala", {"equipe": equipe, "inicio": inicio, "fim": fim}),
                      ensure_ascii=False)


@function_tool
async def tabela_diarias(tipo_destino: str) -> str:
    """Moeda e valor da diária para o tipo de destino: capital, interior ou exterior."""
    return json.dumps(await chamar_mcp_async("tabela_diarias", {"tipo_destino": tipo_destino}), ensure_ascii=False)


@function_tool
async def consultar_remuneracao(matricula: str) -> str:
    """[RESTRITA] Salário-base de um servidor. Só para calcular a venda de férias (N2)."""
    print(f"[tool] consultar_remuneracao({matricula}) EXECUTOU")  # o 🆕 B prova que, barrada, ela NÃO executa
    return json.dumps(await chamar_mcp_async("consultar_remuneracao", {"matricula": matricula}), ensure_ascii=False)


@function_tool
def cotacao_dolar() -> str:
    """Cotação atual do dólar em reais (USD->BRL). Devolve 'indisponível' se a API falhar: nunca invente o câmbio."""
    cotacao = cotacao_usd_brl()
    return f"{cotacao:.4f}" if cotacao else "indisponível"


# ------------------------------------------------------------------ ETAPA 6.1: especialistas
def criar_normas() -> Agent:
    # ETAPA 6.1 -- Agent(name="Normas", instructions=..., tools=[consultar_normas], model_settings=CONFIG)
    #   Responsabilidade: dizer QUAIS regras se aplicam ao pedido e explicá-las em linguagem simples.
    #   NÃO calcula valores, NÃO consulta a escala. Recebe também as violações objetivas (etapa06_regras.py) para explicá-las.
    return Agent(
        name="Normas",
        instructions=(
            "Você é o especialista em NORMAS do RH. Sua única responsabilidade: dizer quais regras da norma interna "
            "se aplicam ao pedido e explicá-las em linguagem simples. Consulte a tool consultar_normas pelos temas "
            "pertinentes (ex.: ferias, prazos, escala, abono, diaria, aprovacao) e cite os códigos (N1, N2...). "
            "Você recebe as VIOLAÇÕES OBJETIVAS já calculadas em Python: não as recalcule nem as contradiga, apenas "
            "explique cada uma. Liste as regras cumpridas e as violadas. Não calcule valores e não consulte a escala. "
            "Responda em português, em até 6 linhas."
        ),
        tools=[consultar_normas],
        model_settings=CONFIG,
    )


def criar_escala() -> Agent:
    # ETAPA 6.1 -- tools=[consultar_escala]. Confere a N5 e, se houver conflito, SUGERE outro período
    #   (com o mesmo número de dias, começando num dia permitido).
    return Agent(
        name="Escala",
        instructions=(
            "Você é o especialista em ESCALA do RH. Sua única responsabilidade: conferir a regra N5 (no máximo 30% "
            "da equipe afastada no mesmo dia, mínimo 1) com a tool consultar_escala (datas AAAA-MM-DD). Ignore o "
            "próprio servidor na lista de afastados. Se houver conflito, diga com quem e SUGIRA outro período com o "
            "mesmo número de dias, começando depois do fim do afastamento que conflita, numa segunda, terça ou "
            "quarta-feira que não seja véspera de feriado (regra N3). Responda em português, em até 4 linhas."
        ),
        tools=[consultar_escala],
        model_settings=CONFIG,
    )


def criar_financeiro() -> Agent:
    # ETAPA 6.1 -- tools=[tabela_diarias, consultar_remuneracao, cotacao_dolar].
    #   Venda de férias (N2): dias_vendidos x salario_base / 30. Diárias (N7): uma por pernoite + meia no retorno;
    #   no exterior, em USD convertido pela cotação. Mostre a conta. Câmbio indisponível -> "a calcular".
    #   É o ÚNICO agente que vê o salário.
    return Agent(
        name="Financeiro",
        instructions=(
            "Você é o especialista FINANCEIRO do RH e o único que pode ver o salário. Calcule e MOSTRE a conta:\n"
            "- Venda de férias (N2): dias_vendidos x salario_base / 30 (salário pela tool consultar_remuneracao). "
            "Sem dias vendidos, não há valor a pagar e você não consulta o salário.\n"
            "- Diárias (N7): uma diária por dia com pernoite e MEIA diária no dia do retorno da viagem. Conte só "
            "pela data_inicio e data_fim do PEDIDO: pernoites = dias entre elas; o dia data_fim é o retorno "
            "(ex.: viagem de 08 a 11 = 3 diárias + 1/2 = 3,5 diárias). O campo 'retorno' do período é a volta ao "
            "TRABALHO: não o use para diárias. Valor pela tool tabela_diarias. No exterior o valor é em USD: "
            "converta pela tool cotacao_dolar e mostre o total em USD e em reais. Se a cotação estiver "
            "indisponível, escreva 'valor em reais: a calcular' (nunca invente o câmbio).\n"
            "Abono não gera valor. Nunca repita o salário-base no texto: mostre só a conta do valor. "
            "Responda em português, em até 4 linhas, com valores em R$ 0.000,00."
        ),
        tools=[tabela_diarias, consultar_remuneracao, cotacao_dolar],
        model_settings=CONFIG,
    )


def criar_redator() -> Agent:
    # ETAPA 6.1 -- sem tools. Escreve o DESPACHO (deferimento ou indeferimento) usando SÓ os fatos recebidos:
    #   matrícula, período, decisão, regras citadas, valores e, no indeferimento, a sugestão de datas.
    #   Nunca escreve CPF nem dado de saúde (N10). Se receber um feedback (da validação ou da chefia), corrige.
    return Agent(
        name="Redator",
        instructions=(
            "Você é o REDATOR do RH. Escreva o DESPACHO oficial do pedido (DEFERIMENTO ou INDEFERIMENTO), em "
            "português formal, em um único parágrafo de até 6 linhas, usando SÓ os fatos recebidos: não invente "
            "datas, valores nem regras, e não acrescente ressalvas ou dúvidas que não estejam nos fatos. O despacho deve citar: a matrícula do servidor, o período em DD/MM/AAAA, a "
            "decisão (use a palavra 'DEFERIDO' ou 'INDEFERIDO'), as regras aplicadas (N1, N5...), os valores "
            "calculados pelo Financeiro (se houver) e, no indeferimento, a sugestão de novo período (se houver). "
            "Se a aprovação da chefia for necessária, diga que o deferimento depende dela. Nunca escreva CPF, CID ou "
            "qualquer dado de saúde (N10). Se receber um FEEDBACK (da validação ou da chefia), corrija o despacho "
            "seguindo o feedback."
        ),
        model_settings=CONFIG,
    )


# ------------------------------------------------------------------ ETAPA 6.2: coordenador
def criar_coordenador(hooks: RunHooks | None = None, tools_extras: list | None = None) -> Agent:
    # ETAPA 6.2 -- Agent(name="Coordenador", instructions=..., tools=[
    #       criar_normas().as_tool(tool_name="parecer_normas", tool_description=..., hooks=hooks,
    #                              failure_error_function=None),
    #       criar_escala().as_tool(tool_name="parecer_escala", ..., hooks=hooks, failure_error_function=None),
    #       criar_financeiro().as_tool(tool_name="parecer_financeiro", ..., hooks=hooks, failure_error_function=None),
    #       *(tools_extras or [])])
    #   O Coordenador decide QUAIS especialistas consultar (abono não precisa do Financeiro) e junta os pareceres.
    #   hooks=hooks nas as_tool faz o hook do 🆕 B enxergar também as tools DENTRO de cada especialista.
    #   failure_error_function=None: sem isso, um erro dentro do especialista (inclusive o bloqueio do 🆕 B) vira só
    #   um texto de erro para o Coordenador, que segue em frente. Com None, o erro interrompe a execução.
    #   tools_extras serve só para o teste do 🆕 B (dar de propósito consultar_remuneracao ao Coordenador).
    #   Referência: aula4/ex03_agente_as_tool.py
    especialistas = [
        criar_normas().as_tool(
            tool_name="parecer_normas",
            tool_description="Especialista em Normas: quais regras se aplicam ao pedido, cumpridas e violadas.",
            hooks=hooks, failure_error_function=None),
        criar_escala().as_tool(
            tool_name="parecer_escala",
            tool_description=("Especialista em Escala: confere a N5 (afastados da equipe no período) e sugere "
                              "outro período se houver conflito. Use para férias e abono."),
            hooks=hooks, failure_error_function=None),
        criar_financeiro().as_tool(
            tool_name="parecer_financeiro",
            tool_description=("Especialista Financeiro: calcula o valor da venda de férias (N2) ou das diárias (N7). "
                              "Use SÓ quando houver dias vendidos ou diária."),
            hooks=hooks, failure_error_function=None),
    ]
    return Agent(
        name="Coordenador",
        instructions=(
            "Você coordena a análise de um pedido ao RH e monta um PARECER único. Consulte só os especialistas "
            "necessários, passando a cada um os fatos do pedido (matrícula, equipe, tipo, datas, dias vendidos, "
            "destino e as violações objetivas):\n"
            "- parecer_normas: sempre;\n"
            "- parecer_escala: férias e abono (diária não afasta o servidor da escala);\n"
            "- parecer_financeiro: só se houver dias vendidos (venda de férias) ou se for diária.\n"
            "Depois junte os pareceres em um texto curto, dizendo de qual especialista veio cada parte. Não decida "
            "o deferimento: as violações objetivas recebidas já dizem se há impedimento. Você não vê o salário de "
            "propósito (só o Financeiro vê): use o valor calculado pelo Financeiro sem questioná-lo."
        ),
        tools=[*especialistas, *(tools_extras or [])],
        model_settings=CONFIG,
    )
