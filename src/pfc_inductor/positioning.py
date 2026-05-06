"""Single source of truth for the project's competitive positioning.

Both `docs/POSITIONING.md` and `ui/about_dialog.py` read from this module so
the differential matrix can never drift between user-facing surfaces.

Edit cadence: revisit every six months (open-source moves; FEMMT may add
cost models, etc.). When a competitor closes a gap, mark coverage to
"partial" or "yes" and re-think the differential's strategic value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Coverage = Literal["yes", "partial", "no", "na"]


@dataclass(frozen=True)
class Competitor:
    id: str
    name: str
    short: str
    url: str
    note: str


@dataclass(frozen=True)
class Differential:
    key: str
    title: str
    blurb: str
    coverage: dict[str, Coverage]


COMPETITORS: list[Competitor] = [
    Competitor(
        id="femmt",
        name="FEMMT (Paderborn LEA)",
        short="FEMMT",
        url="https://github.com/upb-lea/FEM_Magnetics_Toolbox",
        note="Open-source FEM toolbox — main technical peer.",
    ),
    Competitor(
        id="mas",
        name="OpenMagnetics MAS",
        short="MAS",
        url="https://github.com/OpenMagnetics/MAS",
        note="JSON-Schema standard for magnetics. Data, not app.",
    ),
    Competitor(
        id="aimag",
        name="AI-mag (ETH Zurich)",
        short="AI-mag",
        url="https://github.com/ethz-pes/AI-mag",
        note="ANN-trained inductor optimizer. MATLAB. Unmaintained since 2020.",
    ),
    Competitor(
        id="frenetic",
        name="Frenetic AI",
        short="Frenetic",
        url="https://www.frenetic.ai",
        note="Commercial cloud optimizer. Closed-source.",
    ),
    Competitor(
        id="magnetics_designer",
        name="Magnetics Inc Designer",
        short="MagInc",
        url="https://www.mag-inc.com/Design/Software-Designer",
        note="Vendor calculator. Restricted to Magnetics Inc parts.",
    ),
    Competitor(
        id="coilcraft",
        name="Coilcraft Selector",
        short="Coilcraft",
        url="https://www.coilcraft.com/en-us/tools/inductor-finder/",
        note="Vendor parts selector. Restricted to Coilcraft.",
    ),
]


DIFFERENTIALS: list[Differential] = [
    Differential(
        key="pfc_topology",
        title="PFC topology specialização",
        blurb=(
            "Matemática de boost CCM e choke passivo de linha embutidas "
            "end-to-end (forma de onda real iL(t), worst-case low-line, "
            "ripple D(t)). Outros tools são genéricos."
        ),
        coverage={
            "femmt": "no", "mas": "na", "aimag": "no",
            "frenetic": "partial", "magnetics_designer": "no", "coilcraft": "no",
        },
    ),
    Differential(
        key="cost_model",
        title="Modelo de custo no otimizador",
        blurb=(
            "$/kg de material + $/m de fio na função objetivo do "
            "Pareto. Frenetic cobra caro por isso; ferramentas open "
            "não têm."
        ),
        coverage={
            "femmt": "no", "mas": "na", "aimag": "no",
            "frenetic": "yes", "magnetics_designer": "no", "coilcraft": "no",
        },
    ),
    Differential(
        key="litz_optimizer",
        title="Otimizador de Litz com critério Sullivan",
        blurb=(
            "Recomenda d_strand e n_strands para AC/DC alvo, salva "
            "como novo fio. Built-in, sem deps."
        ),
        coverage={
            "femmt": "partial", "mas": "na", "aimag": "no",
            "frenetic": "yes", "magnetics_designer": "no", "coilcraft": "no",
        },
    ),
    Differential(
        key="multi_compare",
        title="Comparar 2-4 designs lado a lado",
        blurb=(
            "Diff-aware highlighting (verde/vermelho), export "
            "HTML/CSV. Estilo Magnetics Designer, mas sem amarrar a "
            "vendor."
        ),
        coverage={
            "femmt": "no", "mas": "na", "aimag": "no",
            "frenetic": "partial", "magnetics_designer": "yes", "coilcraft": "no",
        },
    ),
    Differential(
        key="bh_loop",
        title="Loop B–H no operating point",
        blurb=(
            "Trajetória ao longo do meio-ciclo de rede + segmento "
            "do ripple, sobre a curva estática. Valida visualmente "
            "saturation margin."
        ),
        coverage={
            "femmt": "no", "mas": "na", "aimag": "no",
            "frenetic": "no", "magnetics_designer": "no", "coilcraft": "no",
        },
    ),
    Differential(
        key="polished_ux",
        title="UX moderna PySide6 com light/dark",
        blurb=(
            "Design system Linear/Notion-style, 3D core viewer, "
            "icones SVG inline, alta densidade de informação. "
            "Apps de engenharia geralmente são feios."
        ),
        coverage={
            "femmt": "partial", "mas": "na", "aimag": "no",
            "frenetic": "yes", "magnetics_designer": "partial", "coilcraft": "yes",
        },
    ),
    Differential(
        key="br_market",
        title="Vendors brasileiros + UI em português",
        blurb=(
            "Thornton e Magmattec na base de dados, terminologia "
            "técnica em PT-BR. Mercado que ninguém atende."
        ),
        coverage={
            "femmt": "no", "mas": "no", "aimag": "no",
            "frenetic": "no", "magnetics_designer": "no", "coilcraft": "no",
        },
    ),
]


PITCH = (
    "Ferramenta especializada em projeto de indutores de PFC para "
    "inversores de compressores de geladeira (200–2000 W, entrada "
    "universal). Fiel à física (rolloff DC bias, iGSE, Dowell, "
    "térmico iterativo) e desenhada para o engenheiro decidir, não "
    "só calcular."
)


def get_competitor(cid: str) -> Competitor:
    for c in COMPETITORS:
        if c.id == cid:
            return c
    raise KeyError(cid)


def coverage_label(c: Coverage) -> str:
    return {
        "yes": "✓",
        "partial": "≈",
        "no": "✗",
        "na": "—",
    }[c]
