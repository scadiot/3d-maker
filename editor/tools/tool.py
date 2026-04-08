"""Base Tool class for interactive editor tools."""


class Tool:
    """Abstract base class for interactive editor tools.

    Each tool manages its own state and exposes a uniform interface
    for lifecycle (activate/deactivate), input (mouse/keyboard), and rendering.
    """

    name: str = ""              # Override in subclasses with a unique identifier
    captures_mouse_down: bool = False  # Set to True if the tool intercepts mouse-down

    def __init__(self, app):
        self.app = app

    # ── Convenience accessors ─────────────────────────────────────────────────

    @property
    def state(self):
        return self.app.state

    @property
    def camera(self):
        return self.app.camera

    @property
    def history(self):
        return self.app.history

    @property
    def scene(self):
        return self.app.scene

    @property
    def gizmo(self):
        return self.app.gizmo

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self) -> None:
        """Enter this tool mode."""

    def deactivate(self) -> None:
        """Exit this tool mode, discarding any in-progress operation."""

    def confirm(self) -> None:
        """Confirm the in-progress operation (Enter key)."""

    def cancel(self) -> None:
        """Cancel the in-progress operation (Escape key)."""
        self.deactivate()

    # ── Input ─────────────────────────────────────────────────────────────────

    def on_mouse_down(self, mx: int, my: int) -> None:
        """Called on left mouse-button press inside the viewport."""

    def on_mouse_up(self, mx: int, my: int) -> None:
        """Called on left mouse-button release."""

    def update(self, mx: int, my: int) -> None:
        """Called every frame while the tool is active."""

    # ── Toolbar integration ───────────────────────────────────────────────────

    @property
    def toolbar_button_specs(self) -> list:
        """Button specs for the second toolbar. Override in subclasses.

        Each spec is a dict with:
          label:   str       — button text
          command: callable  — click handler
          visible: callable  — () -> bool, show/hide button and its separator
          enabled: callable  — () -> bool, optional, defaults to always enabled
        """
        return []

    # ── Side panel ────────────────────────────────────────────────────────────

    def build_panel(self, parent) -> bool:
        """Populate *parent* (a tk.Frame) with tool-specific widgets.

        Called each time this tool becomes active.  Return True if at least one
        widget was added (the panel is then shown); return False to hide it.
        """
        return False

    # ── Rendering ─────────────────────────────────────────────────────────────

    def draw(self) -> None:
        """Draw any overlays for this tool (called inside the GL render loop)."""
