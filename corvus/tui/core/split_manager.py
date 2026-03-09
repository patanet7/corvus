"""Split mode manager — tracks side-by-side agent pane assignments."""


class SplitManager:
    """Manages split-pane state for the TUI.

    When active, messages are routed to left or right pane based on agent.
    Unknown agents default to the left pane.
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._left_agent: str = ""
        self._right_agent: str = ""

    @property
    def active(self) -> bool:
        return self._active

    @property
    def left_agent(self) -> str:
        return self._left_agent

    @property
    def right_agent(self) -> str:
        return self._right_agent

    @property
    def display_label(self) -> str:
        """Return a status label like 'SPLIT: @homelab + @finance', or '' if inactive."""
        if not self._active:
            return ""
        return f"SPLIT: @{self._left_agent} + @{self._right_agent}"

    def activate(self, left_agent: str, right_agent: str) -> None:
        """Activate split mode with two agents."""
        self._active = True
        self._left_agent = left_agent
        self._right_agent = right_agent

    def deactivate(self) -> None:
        """Deactivate split mode."""
        self._active = False
        self._left_agent = ""
        self._right_agent = ""

    def swap(self) -> None:
        """Swap the left and right pane agents."""
        self._left_agent, self._right_agent = self._right_agent, self._left_agent

    def pane_for(self, agent_name: str) -> str:
        """Return 'left' or 'right' for a given agent name."""
        if agent_name == self._right_agent:
            return "right"
        return "left"
