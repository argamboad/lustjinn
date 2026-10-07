"""Sign in: the username and password for a token the client keeps on this machine."""

from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Input, Static

from lustjinn_tui.api import ApiError, UnreachableError
from lustjinn_tui.legend import Hint
from lustjinn_tui.status import Kind
from lustjinn_tui.view import View


class SignInScreen(View):
    TITLE = "Sign in"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Enter", "Sign in"),
        Hint("Tab", "Next field"),
        Hint("Esc", "Quit"),
    )
    AUTO_FOCUS: ClassVar[str | None] = "#username"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Quit", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    SignInScreen #body { padding: 2 4; }
    SignInScreen .note { color: $muted; margin-bottom: 1; }
    SignInScreen Input { width: 40; margin-bottom: 1; }
    """

    def __init__(self, note: str | None = None) -> None:
        super().__init__()
        self._note = note

    def body(self) -> ComposeResult:
        yield Static(self._note or f"Sign in to {self.lustjinn.api.server}.", classes="note")
        yield Input(placeholder="username", id="username")
        yield Input(placeholder="password", password=True, id="password")

    @on(Input.Submitted, "#username")
    def _to_password(self) -> None:
        if self.query_one("#password", Input).value:
            self.run_worker(self._submit(), exclusive=True)
        else:
            self.query_one("#password", Input).focus()

    @on(Input.Submitted, "#password")
    def _submit_password(self) -> None:
        self.run_worker(self._submit(), exclusive=True)

    async def _submit(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not username or not password:
            self.status("Both the username and the password are needed.", Kind.WARNING)
            return
        self.status_line.busy("Signing in")
        try:
            await self.lustjinn.api.sign_in(username, password)
        except ApiError as refused:
            self.status_line.idle()
            self.status(refused.detail, Kind.ERROR)
            self.query_one("#password", Input).value = ""
            self.query_one("#password", Input).focus()
        except UnreachableError:
            self.status_line.idle()
            self.lustjinn.lost("The server stopped answering while you signed in.")
        else:
            self.status_line.idle()
            self.lustjinn.signed_in()

    def action_back(self) -> None:
        self.lustjinn.exit()
