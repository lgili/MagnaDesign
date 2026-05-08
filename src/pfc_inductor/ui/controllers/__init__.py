"""Thin controller layer between the UI shell (``MainWindow``) and the
domain (``design.engine``, ``data_loader``).

The goal is to keep ``MainWindow`` focused on Qt wiring (signals,
layout, theme refresh) and push every "read panel state → call domain →
return DTO" pipeline into a controller class. Each controller is a
plain Python object — no Qt inheritance — so it is unit-testable
without spinning up a ``QApplication``.
"""

from __future__ import annotations

from pfc_inductor.ui.controllers.calculation_controller import (
    CalculationController,
    CalculationInputs,
)

__all__ = ["CalculationController", "CalculationInputs"]
