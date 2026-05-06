"""Structural typing for dashboard surfaces.

The :class:`DesignDisplay` Protocol formalizes the contract that every
card mounted in :class:`~pfc_inductor.ui.dashboard.dashboard_page.DashboardPage`
honours: a fan-out ``update_from_design`` and a ``clear`` reset.

Why a Protocol and not an ABC:

- Cards inherit from :class:`~pfc_inductor.ui.widgets.card.Card`
  (which itself extends ``QFrame``), and adding a second base would
  trip Qt's metaclass machinery. Protocols give us static structural
  typing without runtime mixin gymnastics.
- ``DashboardPage._cards: list[DesignDisplay]`` lets mypy/pyright
  catch a card that forgets to implement either method, instead of
  the previous ``list[QFrame]`` which silently allowed any widget.

Adoption is incremental: existing cards already match the shape, so
typing ``_cards`` as ``list[DesignDisplay]`` is a drop-in change.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


@runtime_checkable
class DesignDisplay(Protocol):
    """Every dashboard card honours this contract."""

    def update_from_design(
        self,
        result: DesignResult,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        ...

    def clear(self) -> None:
        ...
