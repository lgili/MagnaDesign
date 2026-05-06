"""Workspace pages — Projeto / Otimizador / Catálogo / Configurações.

Each module exposes a top-level ``QWidget`` used as a page in
``MainWindow``'s ``QStackedWidget``. The Projeto page itself contains a
``QTabWidget`` (Design / Validar / Exportar).
"""
from pfc_inductor.ui.workspace.projeto_page import ProjetoPage
from pfc_inductor.ui.workspace.otimizador_page import OtimizadorPage
from pfc_inductor.ui.workspace.catalogo_page import CatalogoPage
from pfc_inductor.ui.workspace.configuracoes_page import ConfiguracoesPage

__all__ = ["ProjetoPage", "OtimizadorPage", "CatalogoPage", "ConfiguracoesPage"]
