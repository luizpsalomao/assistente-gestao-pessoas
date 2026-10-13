"""
ETAPA 2 -- Extração estruturada do pedido (15 min) e 🆕 A -- votação em paralelo (OPCIONAL, bônus).

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 2.1 -- complete o modelo Pydantic `Pedido` (campos + Field(description=...))
  ETAPA 2.2 -- criar_extrator(): um Agent com output_type=Pedido
  ETAPA 2.3 -- extrair(): roda UM extrator e devolve um Pedido
  --- daqui para baixo é OPCIONAL (item 🆕 A, vale bônus). Pule se estiver sem tempo: o resto do sistema não depende dele.
  🆕 A.1    -- INSTRUCOES_VOTANTES: 3 instruções ligeiramente diferentes
  🆕 A.2    -- extrair_com_votacao(): os 3 extratores AO MESMO TEMPO (asyncio.gather)
  (PRONTO)  -- votar(): maioria por campo; sem maioria em tipo/datas -> divergencia=True
  (PRONTO)  -- no __main__: o tempo em paralelo x em sequência

REFERÊNCIAS NAS AULAS
  aula2/agente_output.py                   output_type com um BaseModel simples
  aula2/agente_output2.py                  Enum + listas + Field(description=...)          <- o mais parecido
  aula7/exemplos/08_paralelismo/main.py    🆕 A: o CONCEITO de paralelismo (lá: tarefas DIFERENTES para ganhar tempo;
                                           aqui: a MESMA tarefa 3 vezes para ganhar confiabilidade)
  aula3/agente_parada3.py                  Runner.run (assíncrono) dentro de asyncio, como em A.2
  aula3/agente_retry.py                    por que a data de hoje entra nas instruções (já feito abaixo, com texto_hoje())

Rodar:
    python etapa02_extracao.py            # extrai C1, C2, C5 e C11
    python etapa02_extracao.py --votacao  # 🆕 A: C1, C2 e C9 com 3 votos e o tempo medido

Pronto quando: C2 sai com dias_vendidos=10, C11 com tipo_destino="exterior", C5 com matricula=None;
               na votação, C1/C2 unânimes e C9 mostrando os votos.
"""
import asyncio
import sys
import time
from collections import Counter
from enum import Enum

from agents import Agent, Runner
from pydantic import BaseModel, Field

from dados.casos import CASOS
from etapa04_ferramentas import texto_hoje
from provedor import configurar

MODELO = configurar()


class TipoPedido(str, Enum):
    FERIAS = "ferias"
    ABONO = "abono"
    DIARIA = "diaria"
    LICENCA_SAUDE = "licenca_saude"
    OUTRO = "outro"


class TipoDestino(str, Enum):
    CAPITAL = "capital"
    INTERIOR = "interior"
    EXTERIOR = "exterior"


class Pedido(BaseModel):
    # ETAPA 2.1 -- complete os campos. O primeiro já está pronto como modelo.
    #   matricula: str | None          (4 dígitos; None se o servidor não informou)
    #   data_inicio: str | None        (AAAA-MM-DD)
    #   data_fim: str | None           (AAAA-MM-DD; no abono, igual à data_inicio)
    #   dias_vendidos: int             (0 a 10; abono pecuniário, regra N2 -- use Field(default=0, ge=0, le=10, ...))
    #   destino: str | None            (só para diária: a cidade)
    #   tipo_destino: TipoDestino | None
    #   justificativa: str             (resumo do motivo, sem dados de saúde)
    #   Escreva a DESCRIPTION de cada um: é a "instrução" que o LLM lê para preencher o campo.
    #   Referência: aula2/agente_output2.py (Ocorrencia, Envolvido, PapelEnvolvido)
    tipo: TipoPedido = Field(description=(
        "Tipo do pedido: 'ferias' (descanso anual, pode incluir venda de dias), 'abono' (folga de 1 dia útil), "
        "'diaria' (viagem a serviço), 'licenca_saude' (afastamento por doença) ou 'outro'."))
    matricula: str | None = Field(default=None, description=(
        "Matrícula do servidor, 4 dígitos (ex.: '1002'), exatamente como escrita no texto. "
        "null se o servidor não informou a matrícula: nunca invente."))
    data_inicio: str | None = Field(default=None, description=(
        "Primeiro dia do pedido, no formato AAAA-MM-DD. Só preencha se o servidor disse o DIA exato; "
        "'em agosto', 'perto da Páscoa' ou 'semana que vem' NÃO são datas exatas: use null."))
    data_fim: str | None = Field(default=None, description=(
        "Último dia do pedido, no formato AAAA-MM-DD. No abono (1 dia), igual à data_inicio. Se o servidor deu o "
        "dia de início e a DURAÇÃO exata (ex.: '20 dias a partir de amanhã'), calcule: início + duração - 1. "
        "null se não há como saber o dia exato."))
    dias_vendidos: int = Field(default=0, ge=0, le=10, description=(
        "Dias de férias que o servidor quer VENDER (abono pecuniário, regra N2), de 0 a 10. "
        "Só preencha se ele pediu explicitamente para vender um número de dias; caso contrário, 0."))
    destino: str | None = Field(default=None, description=(
        "Só para diária: a cidade da viagem a serviço (ex.: 'Buenos Aires'). null nos demais tipos."))
    tipo_destino: TipoDestino | None = Field(default=None, description=(
        "Só para diária: 'capital' (capital brasileira), 'interior' (outra cidade do Brasil) ou 'exterior' "
        "(fora do Brasil). null nos demais tipos."))
    justificativa: str = Field(default="", description=(
        "Resumo curto do motivo do pedido, em uma frase. NUNCA inclua CPF, CID ou detalhes de saúde (regra N10)."))


def criar_extrator(instrucoes: str, input_guardrails: list | None = None) -> Agent:
    # ETAPA 2.2 -- devolva Agent(name="Extrator", instructions=instrucoes, output_type=Pedido,
    #   input_guardrails=input_guardrails or [])
    #   (os guardrails só entram na Etapa 3; até lá, a lista fica vazia)
    return Agent(name="Extrator", instructions=instrucoes, output_type=Pedido,
                 input_guardrails=input_guardrails or [])


INSTRUCOES_EXTRATOR = (
    f"Hoje é {texto_hoje()}. "  # (PRONTO) a data real: o modelo não tem relógio (aula3/agente_retry.py)
    "Você extrai pedidos de servidores para o RH (férias, abono ou diária). "
    "Preencha os campos só com o que está escrito no texto. Datas sempre no formato AAAA-MM-DD, e só quando o "
    "servidor disse o dia exato. Não invente nada que não foi dito: matrícula, datas ou destino ausentes ficam null. "
    "Dias vendidos só se o servidor pedir explicitamente para vender; caso contrário, 0."
)


def extrair(texto: str) -> Pedido:
    # ETAPA 2.3 -- rode criar_extrator(INSTRUCOES_EXTRATOR) com Runner.run_sync e devolva final_output
    #   (é um objeto Pedido, não texto!)
    resultado = Runner.run_sync(criar_extrator(INSTRUCOES_EXTRATOR), texto)
    ULTIMO_USO["tokens"] = resultado.context_wrapper.usage.total_tokens  # para a observabilidade (Etapa 10)
    return resultado.final_output


ULTIMO_USO = {"tokens": 0}  # tokens da última extração (o nó extrair do grafo lê daqui)


# ------------------------------------------------------------------ 🆕 A: votação (OPCIONAL, bônus)
# Para ligar no grafo depois de pronto: USAR_VOTACAO = True em etapa07_grafo.py.
# 🆕 A.1 -- três instruções LIGEIRAMENTE diferentes para a MESMA tarefa (comece cada uma com f"Hoje é {texto_hoje()}. ")
#   ex.: um extrator literal; um que confere as datas contra o calendário; um que "pensa como o RH".
INSTRUCOES_VOTANTES: list[str] = []  # TODO 🆕 A.1: preencha com 3 strings


async def extrair_com_votacao(texto: str) -> tuple[Pedido, bool, list[Pedido]]:
    # 🆕 A.2 -- crie os 3 extratores e rode-os AO MESMO TEMPO:
    #     resultados = await asyncio.gather(*(Runner.run(e, texto) for e in extratores))
    #   depois chame votar([r.final_output for r in resultados]) e devolva (pedido_final, divergencia, votos).
    #   Conceito: aula7/exemplos/08_paralelismo/main.py (fan-out/fan-in), aqui em asyncio, sem grafo.
    raise NotImplementedError("🆕 A.2: extrair_com_votacao")


def votar(votos: list[Pedido]) -> tuple[Pedido, bool]:
    """(PRONTO) Maioria por campo. Sem maioria (2 de 3) em `tipo` ou nas datas -> divergencia=True: o sistema vai
    pedir esclarecimento em vez de adivinhar. Os campos não votados vêm do primeiro voto."""
    decidido, divergencia = {}, False
    for campo in ("tipo", "matricula", "data_inicio", "data_fim", "dias_vendidos"):
        valor, quantos = Counter(getattr(voto, campo) for voto in votos).most_common(1)[0]
        decidido[campo] = valor
        if quantos < 2 and campo in ("tipo", "data_inicio", "data_fim"):
            divergencia = True
    return votos[0].model_copy(update=decidido), divergencia


def _demo_extracao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C5_sem_matricula", "C11_diaria_exterior"):
        pedido = extrair(CASOS[nome]["pedido"])
        print(f"\n{nome}\n  {pedido.model_dump()}")


def _demo_votacao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C9_divergencia"):
        texto = CASOS[nome]["pedido"]
        inicio = time.perf_counter()
        pedido, divergencia, votos = asyncio.run(extrair_com_votacao(texto))
        segundos = time.perf_counter() - inicio
        print(f"\n{nome}  ({segundos:.1f}s, divergencia={divergencia})")
        for i, voto in enumerate(votos, 1):
            print(f"  voto {i}: tipo={voto.tipo.value} {voto.data_inicio}..{voto.data_fim} vende={voto.dias_vendidos}")
        print(f"  decisão: {pedido.model_dump()}")
    # (PRONTO) os mesmos 3 extratores EM SEQUÊNCIA, para comparar: o paralelo fica perto do tempo de UMA chamada?
    texto = CASOS["C2_ferias_com_venda"]["pedido"]
    inicio = time.perf_counter()
    for instrucoes in INSTRUCOES_VOTANTES:
        Runner.run_sync(criar_extrator(instrucoes), texto)
    print(f"\nC2 em sequência: {time.perf_counter() - inicio:.1f}s (compare com o tempo do C2 em paralelo, acima)")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    _demo_votacao() if "--votacao" in sys.argv else _demo_extracao()
