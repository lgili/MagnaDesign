"""Application-shell widgets used by the new MagnaDesign layout."""
from pfc_inductor.ui.shell.header import WorkspaceHeader
from pfc_inductor.ui.shell.sidebar import SIDEBAR_AREAS, Sidebar
from pfc_inductor.ui.shell.status_bar import BottomStatusBar
from pfc_inductor.ui.shell.stepper import STEP_STATES, WorkflowStepper

__all__ = [
    "Sidebar", "SIDEBAR_AREAS",
    "WorkspaceHeader",
    "WorkflowStepper", "STEP_STATES",
    "BottomStatusBar",
]
