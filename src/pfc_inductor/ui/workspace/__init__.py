"""Workspace pages — Projeto / Otimizador / Catálogo / Configurações.

Each module exposes a top-level ``QWidget`` used as a page in
``MainWindow``'s ``QStackedWidget``. The Projeto page itself contains
the four-tab workspace (Núcleo / Análise / Validar / Exportar).
"""
from pfc_inductor.ui.workspace.analise_page import AnalisePage
from pfc_inductor.ui.workspace.catalogo_page import CatalogoPage
from pfc_inductor.ui.workspace.configuracoes_page import ConfiguracoesPage
from pfc_inductor.ui.workspace.nucleo_selection_page import NucleoSelectionPage
from pfc_inductor.ui.workspace.otimizador_page import OtimizadorPage
from pfc_inductor.ui.workspace.projeto_page import ProjetoPage

__all__ = [
    "AnalisePage",
    "CatalogoPage",
    "ConfiguracoesPage",
    "NucleoSelectionPage",
    "OtimizadorPage",
    "ProjetoPage",
]
