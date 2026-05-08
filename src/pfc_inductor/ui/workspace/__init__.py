"""Workspace pages — Project / Optimizer / Catalog / Settings.

Each module exposes a top-level ``QWidget`` used as a page in
``MainWindow``'s ``QStackedWidget``. The Project page itself contains
the four-tab workspace (Core / Analysis / Validate / Export).
"""
from pfc_inductor.ui.workspace.analise_page import AnalisePage
from pfc_inductor.ui.workspace.cascade_page import CascadePage
from pfc_inductor.ui.workspace.catalogo_page import CatalogoPage
from pfc_inductor.ui.workspace.configuracoes_page import ConfiguracoesPage
from pfc_inductor.ui.workspace.nucleo_selection_page import NucleoSelectionPage
from pfc_inductor.ui.workspace.otimizador_page import OtimizadorPage
from pfc_inductor.ui.workspace.projeto_page import ProjetoPage

__all__ = [
    "AnalisePage",
    "CascadePage",
    "CatalogoPage",
    "ConfiguracoesPage",
    "NucleoSelectionPage",
    "OtimizadorPage",
    "ProjetoPage",
]
