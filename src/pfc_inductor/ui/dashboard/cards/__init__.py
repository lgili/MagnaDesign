"""Per-card body widgets for the dashboard.

Each card body exposes ``update_from_design(result, spec, core, wire,
material)`` and ``clear()``. The :class:`DashboardPage
<pfc_inductor.ui.dashboard.DashboardPage>` orchestrates them.
"""

from pfc_inductor.ui.dashboard.cards.bh_loop_card import BHLoopCard
from pfc_inductor.ui.dashboard.cards.bobinamento_card import BobinamentoCard
from pfc_inductor.ui.dashboard.cards.detalhes_tecnicos_card import DetalhesTecnicosCard
from pfc_inductor.ui.dashboard.cards.entreferro_card import EntreferroCard
from pfc_inductor.ui.dashboard.cards.formas_onda_card import FormasOndaCard
from pfc_inductor.ui.dashboard.cards.l_current_card import LCurrentCard
from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
from pfc_inductor.ui.dashboard.cards.perdas_card import PerdasCard
from pfc_inductor.ui.dashboard.cards.pf_inductance_card import PFvsLCard
from pfc_inductor.ui.dashboard.cards.power_inductance_card import PowerInductanceCard
from pfc_inductor.ui.dashboard.cards.proximos_passos_card import ProximosPassosCard
from pfc_inductor.ui.dashboard.cards.resumo_card import ResumoCard
from pfc_inductor.ui.dashboard.cards.thermal_gauge_card import ThermalGaugeCard
from pfc_inductor.ui.dashboard.cards.topologia_card import TopologiaCard
from pfc_inductor.ui.dashboard.cards.viz3d_card import Viz3DCard

__all__ = [
    "BHLoopCard",
    "BobinamentoCard",
    "DetalhesTecnicosCard",
    "EntreferroCard",
    "FormasOndaCard",
    "LCurrentCard",
    "NucleoCard",
    "PFvsLCard",
    "PerdasCard",
    "PowerInductanceCard",
    "ProximosPassosCard",
    "ResumoCard",
    "ThermalGaugeCard",
    "TopologiaCard",
    "Viz3DCard",
]
