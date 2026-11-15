"""
Tratamento de textos legislativos compilados (padrão do Planalto).

O texto compilado traz todas as redações que um dispositivo já teve, em
ordem cronológica: a original, as alterações ("Redação dada pela ...") e
até redações de medidas provisórias que perderam a vigência. Para a busca
só interessa a redação vigente. Este módulo:

  1. reconhece a estrutura: artigo > parágrafo > inciso > alínea > item;
  2. quando um dispositivo reaparece sob o mesmo pai, a redação nova
     substitui a anterior (junto com os filhos dela);
  3. reduz dispositivos revogados ao rótulo + nota de revogação;
  4. divide o texto por artigo, sem misturar artigos no mesmo chunk.
"""
import math
import re
from dataclasses import dataclass, field
from typing import List, Tuple

# (nível, padrão). O grupo 1 é o rótulo; os demais formam a chave.
_PADROES = [
    (0, re.compile(r"^(Art\.?\s*(\d+)\s*[º°o]?\s*(?:-\s*([A-Z]))?)\s*\.?(?=\s|$)")),
    (1, re.compile(r"^(§\s*(\d+)\s*[º°o]?\s*(?:-\s*([A-Z]))?)\s*\.?(?=\s|$)")),
    (1, re.compile(r"^(Par[áa]grafo\s+[úu]nico)\s*\.?(?=\s|$)", re.I)),
    (2, re.compile(r"^(([IVXLC]+)(?:-([A-Z]))?\s*[-–—])")),
    (3, re.compile(r"^(([a-z])(?:-([A-Z]))?\))")),
    (4, re.compile(r"^((\d+)\s*[.)])(?=\s)")),
]

_TITULO = re.compile(r"^(LIVRO|T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\b", re.I)
_EPILOGO = re.compile(r"^Bras[íi]lia\s*,")
_REVOGACAO = re.compile(r"\((?:Revogad|Suprimid)[oa]s?\b[^)]*\)", re.I)

# tamanho máximo do caput repetido no início dos chunks de um artigo longo
_LIMITE_CABECALHO = 160


@dataclass
class _Dispositivo:
    nivel: int
    chave: str
    rotulo: str
    texto: str
    filhos: List["_Dispositivo"] = field(default_factory=list)

    @property
    def nota_revogacao(self) -> str | None:
        notas = _REVOGACAO.findall(self.texto)
        if notas and "vigência encerrada" not in self.texto.lower():
            return notas[-1]
        return None

    def linhas(self) -> List[str]:
        nota = self.nota_revogacao
        if nota:
            # revogado: filhos caem junto com o dispositivo
            return [f"{self.rotulo} {nota}"]
        linhas = [f"{self.rotulo} {self.texto}".strip()]
        for filho in self.filhos:
            linhas.extend(filho.linhas())
        return linhas


def _normalizar(linha: str) -> str:
    return re.sub(r"\s+", " ", linha).strip()


def _identificar(linha: str) -> Tuple[int, str, str, str] | None:
    for tipo, (nivel, padrao) in enumerate(_PADROES):
        m = padrao.match(linha)
        if m:
            # o tipo entra na chave: § 1º e item "1." não são o mesmo dispositivo
            numero = "".join(g or "" for g in m.groups()[1:]).lower()
            rotulo = _normalizar(linha[: m.end()])
            return nivel, f"{tipo}:{numero}", rotulo, linha[m.end():].strip()
    return None


def eh_texto_legal(texto: str, minimo_artigos: int = 3) -> bool:
    """Heurística: o texto tem cara de lei se tiver vários 'Art. N' no início de linha."""
    padrao_artigo = _PADROES[0][1]
    total = sum(1 for l in texto.splitlines() if padrao_artigo.match(l.strip()))
    return total >= minimo_artigos


def extrair_artigos(texto: str) -> Tuple[List[List[str]], str]:
    """
    Devolve (artigos, texto_fora).
      artigos:    cada artigo como lista de linhas, só com a redação vigente
      texto_fora: o que não pertence a artigos (ementa, preâmbulo, assinaturas)
    Títulos, capítulos e seções são descartados.
    """
    artigos: List[_Dispositivo] = []
    fora: List[str] = []
    pilha: List[_Dispositivo] = []
    em_titulo = False
    em_epilogo = False

    for bruta in texto.splitlines():
        linha = _normalizar(bruta)
        if not linha:
            continue

        if em_epilogo or _EPILOGO.match(linha):
            em_epilogo = True
            fora.append(linha)
            continue

        if _TITULO.match(linha):
            em_titulo, pilha = True, []
            continue

        ident = _identificar(linha)
        if ident is None:
            # linha sem rótulo: continuação do dispositivo anterior
            # (PDFs quebram linhas) ou nome de título/seção
            if pilha and not em_titulo:
                pilha[-1].texto = f"{pilha[-1].texto} {linha}".strip()
            elif not artigos and not em_titulo:
                fora.append(linha)
            continue

        nivel, chave, rotulo, resto = ident
        if nivel > 0 and not pilha:
            # dispositivo solto, fora de artigo
            if not artigos:
                fora.append(linha)
            continue

        em_titulo = False
        while pilha and pilha[-1].nivel >= nivel:
            pilha.pop()
        irmaos = pilha[-1].filhos if pilha else artigos

        novo = _Dispositivo(nivel, chave, rotulo, resto)
        anterior = next((i for i, d in enumerate(irmaos) if d.chave == chave), None)
        if anterior is None:
            irmaos.append(novo)
        else:
            # nova redação do mesmo dispositivo: substitui a antiga
            irmaos[anterior] = novo
        pilha.append(novo)

    return [a.linhas() for a in artigos], "\n\n".join(fora)


def _cabecalho(caput: str) -> str:
    if len(caput) <= _LIMITE_CABECALHO:
        return caput
    return caput[:_LIMITE_CABECALHO].rsplit(" ", 1)[0] + " (…)"


def _fatiar(texto: str, tamanho: int, overlap: int) -> List[str]:
    """
    Fatia um texto longo com sobreposição, cortando entre palavras.
    As partes têm tamanhos parecidos, para não sobrar um fragmento minúsculo.
    """
    n = max(1, math.ceil((len(texto) - overlap) / max(tamanho - overlap, 1)))
    alvo = min(tamanho, math.ceil((len(texto) + (n - 1) * overlap) / n) + 20)

    partes: List[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + alvo, len(texto))
        if fim < len(texto):
            espaco = texto.rfind(" ", inicio + alvo // 2, fim)
            if espaco > inicio:
                fim = espaco
        partes.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        # recua o overlap e recomeça no início de uma palavra
        recuo = max(fim - overlap, inicio + 1)
        espaco = texto.find(" ", recuo, fim)
        inicio = espaco + 1 if espaco != -1 else recuo
    return partes


def dividir_artigo(linhas: List[str], tamanho: int, overlap: int) -> List[str]:
    """
    Um artigo que cabe no tamanho vira um chunk só. Se não couber, é dividido
    nos limites dos dispositivos, e cada chunk depois do primeiro começa com
    o caput (resumido), para o trecho não perder o contexto do artigo.
    Assim todo chunk começa com o rótulo do artigo (ver juntar_artigo).
    """
    texto = "\n".join(linhas)
    if len(texto) <= tamanho:
        return [texto]

    cabecalho = _cabecalho(linhas[0])
    chunks: List[str] = []
    buffer: List[str] = []

    def emitir():
        # um buffer só com o cabeçalho não acrescenta nada
        if buffer and buffer != [cabecalho]:
            chunks.append("\n".join(buffer))

    for i, linha in enumerate(linhas):
        if len("\n".join(buffer + [linha])) <= tamanho:
            buffer.append(linha)
            continue

        emitir()
        buffer = [cabecalho]
        espaco = tamanho - len(cabecalho) - 1
        if i == 0:
            # caput maior que o chunk: a primeira parte já começa pelo rótulo
            partes = _fatiar(linha, espaco, overlap)
            chunks.append(partes[0])
            chunks.extend(f"{cabecalho}\n{parte}" for parte in partes[1:])
        elif len(cabecalho) + 1 + len(linha) <= tamanho:
            buffer.append(linha)
        else:
            chunks.extend(f"{cabecalho}\n{parte}" for parte in _fatiar(linha, espaco, overlap))

    emitir()
    return chunks


def rotulo_do_artigo(chunk: str) -> str | None:
    """Rótulo do artigo no início do chunk ('Art. 16.'), ou None."""
    m = _PADROES[0][1].match(chunk)
    return _normalizar(chunk[: m.end()]) if m else None


def juntar_artigo(chunks: List[str]) -> str:
    """Remonta o artigo a partir dos seus chunks em ordem, sem o caput repetido."""
    if not chunks:
        return ""
    linhas = chunks[0].split("\n")
    for chunk in chunks[1:]:
        linhas.extend(chunk.split("\n")[1:])
    return "\n".join(linhas)
