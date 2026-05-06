"""Application-shell widgets used by the new MagnaDesign layout."""
from pfc_inductor.ui.shell.sidebar import Sidebar, SIDEBAR_AREAS
from pfc_inductor.ui.shell.header import WorkspaceHeader
from pfc_inductor.ui.shell.stepper import WorkflowStepper, STEP_STATES
from pfc_inductor.ui.shell.status_bar import BottomStatusBar

__all__ = [
    "Sidebar", "SIDEBAR_AREAS",
    "WorkspaceHeader",
    "WorkflowStepper", "STEP_STATES",
    "BottomStatusBar",
]
