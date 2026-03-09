"""TerminalLayout — manages terminal screen regions for the Corvus TUI.

Provides a layout manager that partitions the terminal into header, main,
sidebar, and status regions using Rich Layout. Supports three display modes:
SINGLE (main only), SPLIT (two columns), and SIDEBAR (main + right sidebar).
"""

import enum

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text


class LayoutMode(enum.Enum):
    """Display mode for the terminal layout."""

    SINGLE = "single"
    SPLIT = "split"
    SIDEBAR = "sidebar"


class TerminalLayout:
    """Manages terminal screen regions for the Corvus TUI.

    Organises the terminal into four logical regions:

    - header_region: top line showing breadcrumb path
    - main_region: primary content area (chat output)
    - sidebar_region: optional right sidebar (agent tree, tool list)
    - status_region: bottom status bar

    The visible regions depend on the current LayoutMode.
    """

    def __init__(self) -> None:
        self._mode: LayoutMode = LayoutMode.SINGLE

        # Content for each region — callers update these before render.
        self.header_content: str = ""
        self.main_content: str = ""
        self.sidebar_content: str = ""
        self.status_content: str = ""

        # Split mode pane content.
        self.left_content: str = ""
        self.right_content: str = ""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active_mode(self) -> LayoutMode:
        """Return the current layout mode."""
        return self._mode

    @property
    def has_sidebar(self) -> bool:
        """Return True if the current mode shows a sidebar."""
        return self._mode == LayoutMode.SIDEBAR

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def set_mode(self, mode: LayoutMode) -> None:
        """Switch to a different layout mode.

        Args:
            mode: The LayoutMode to activate.

        Raises:
            TypeError: If *mode* is not a LayoutMode instance.
        """
        if not isinstance(mode, LayoutMode):
            raise TypeError(f"Expected LayoutMode, got {type(mode).__name__}")
        self._mode = mode

    # ------------------------------------------------------------------
    # Layout construction helpers
    # ------------------------------------------------------------------

    def _build_header(self) -> Panel:
        """Build the header panel showing the breadcrumb path."""
        return Panel(
            Text(self.header_content, style="bold"),
            height=3,
            style="dim",
            title="corvus",
            title_align="left",
        )

    def _build_status(self) -> Panel:
        """Build the status bar panel."""
        return Panel(
            Text(self.status_content),
            height=3,
            style="dim reverse",
        )

    def _build_main_panel(self, content: str, title: str = "") -> Panel:
        """Build a main-area panel with optional title."""
        return Panel(
            Text(content),
            title=title or None,
            title_align="left",
            border_style="dim",
            expand=True,
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _build_single_body(self) -> Layout:
        """Build body layout for SINGLE mode."""
        body = Layout(name="body")
        body.update(self._build_main_panel(self.main_content))
        return body

    def _build_split_body(self) -> Layout:
        """Build body layout for SPLIT mode — two equal columns."""
        body = Layout(name="body")
        left = Layout(name="left")
        right = Layout(name="right")
        left.update(self._build_main_panel(self.left_content, title="left"))
        right.update(self._build_main_panel(self.right_content, title="right"))
        body.split_row(left, right)
        return body

    def _build_sidebar_body(self) -> Layout:
        """Build body layout for SIDEBAR mode — main (3/4) + sidebar (1/4)."""
        body = Layout(name="body")
        main = Layout(name="main", ratio=3)
        sidebar = Layout(name="sidebar", ratio=1)
        main.update(self._build_main_panel(self.main_content))
        sidebar.update(
            Panel(
                Text(self.sidebar_content),
                title="sidebar",
                title_align="left",
                border_style="dim",
                expand=True,
            )
        )
        body.split_row(main, sidebar)
        return body

    def render(self, console: Console) -> None:
        """Render the current layout to the given Rich Console.

        Builds a full-screen Layout with header, body, and status regions,
        then prints it to *console*.

        Args:
            console: The Rich Console instance to render to.
        """
        root = Layout(name="root")

        header = Layout(name="header", size=3)
        header.update(self._build_header())

        status = Layout(name="status", size=3)
        status.update(self._build_status())

        if self._mode == LayoutMode.SINGLE:
            body = self._build_single_body()
        elif self._mode == LayoutMode.SPLIT:
            body = self._build_split_body()
        elif self._mode == LayoutMode.SIDEBAR:
            body = self._build_sidebar_body()
        else:
            body = self._build_single_body()

        root.split_column(header, body, status)
        console.print(root)
