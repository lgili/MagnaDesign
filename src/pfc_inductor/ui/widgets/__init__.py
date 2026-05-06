"""Reusable dashboard widgets — Card, MetricCard, DataTable, ScorePill,
DonutChart, NextStepsCard."""
from pfc_inductor.ui.widgets.card import Card
from pfc_inductor.ui.widgets.data_table import DataTable
from pfc_inductor.ui.widgets.donut_chart import DonutChart
from pfc_inductor.ui.widgets.metric_card import MetricCard, MetricStatus
from pfc_inductor.ui.widgets.next_steps import ActionItem, ActionStatus, NextStepsCard
from pfc_inductor.ui.widgets.schematic import (
    TopologyKind,
    TopologySchematicWidget,
    topology_picker_choices,
)
from pfc_inductor.ui.widgets.score_pill import ScorePill

__all__ = [
    "Card",
    "MetricCard", "MetricStatus",
    "DataTable",
    "ScorePill",
    "DonutChart",
    "NextStepsCard", "ActionItem", "ActionStatus",
    "TopologySchematicWidget", "TopologyKind", "topology_picker_choices",
]
