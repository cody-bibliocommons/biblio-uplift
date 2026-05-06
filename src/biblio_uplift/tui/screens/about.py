from __future__ import annotations

import contextlib
import platform
import random
from datetime import datetime

from textual.app import ComposeResult
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

import biblio_uplift

QUOTES = [
    '"It works on my machine" — Every developer, ever',
    '"Have you tried turning it off and on again?" — IT Crowd',
    "\"There is no cloud, it's just someone else's computer.\"",
    '"The best time to back up was yesterday. The second best time is now."',
    '"Weeks of coding can save you hours of planning."',
    "\"It's not a bug, it's an undocumented feature.\"",
    '"sudo make me a sandwich"',
    '"There are only two hard things in CS: cache invalidation, naming things, and off-by-one errors."',
    '"chmod 777 fixes everything" — said no sysadmin ever',
    '"I don\'t always test my code, but when I do, I do it in production."',
    '"Works on my machine. Ship it."',
    "\"The cloud is just someone else's computer that's on fire.\"",
    '"Uptime is just the time between incidents."',
    '"DNS: It\'s always DNS."',
    '"Have you checked the logs?" — The answer to everything',
]

TITLE = "[bold]Biblio[/bold] [bold italic]UPLIFT[/bold italic]"

BLACK_MAGE_FRAMES = [
    (
        "[yellow]         ▄         [/]\n"
        "[yellow]        ███        [/]\n"
        "[yellow]       █████       [/]\n"
        "[yellow]      ███████      [/]\n"
        "[yellow]     █████████     [/]\n"
        "[dim]     █████████     [/]\n"
        "[dim]     ██[/][yellow]█[/][dim]███[/][yellow]█[/][dim]██     [/]\n"
        "[dim]     █████████     [/]\n"
        "[blue]      ███████      [/]\n"
        "[blue]     █████████     [/]\n"
        "[blue]    ███████████    [/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]   ██████ ██████   [/]\n"
        "[blue]   ████     ████   [/]\n"
        "[blue]   ███       ███   [/]\n"
        "[dim]   ▄▄▄       ▄▄▄   [/]\n"
        "[dim]  █████     █████  [/]\n"
        "[dim]  ▀▀▀▀▀     ▀▀▀▀▀  [/]"
    ),
    (
        "[yellow]         ▄         [/]\n"
        "[yellow]        ███        [/]\n"
        "[yellow]       █████       [/]\n"
        "[yellow]      ███████      [/]\n"
        "[yellow]     █████████     [/]\n"
        "[dim]     █████████     [/]\n"
        "[dim]     ██[/][yellow]█[/][dim]███[/][yellow]█[/][dim]██     [/]\n"
        "[dim]     █████████     [/]\n"
        "[yellow]★[/]    [blue]███████[/]    [yellow]★[/]\n"
        "[blue] ██  ███████  ██ [/]\n"
        "[blue]  █  ███████  █  [/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]   ██████ ██████   [/]\n"
        "[blue]   ████     ████   [/]\n"
        "[blue]   ███       ███   [/]\n"
        "[dim]   ▄▄▄       ▄▄▄   [/]\n"
        "[dim]  █████     █████  [/]\n"
        "[dim]  ▀▀▀▀▀     ▀▀▀▀▀  [/]"
    ),
    (
        "\n"
        "\n"
        "[yellow]         ▄         [/]\n"
        "[yellow]        ███        [/]\n"
        "[yellow]       █████       [/]\n"
        "[yellow]      ███████      [/]\n"
        "[yellow]     █████████     [/]\n"
        "[dim]     █████████     [/]\n"
        "[dim]     ██[/][yellow]█[/][dim]███[/][yellow]█[/][dim]██     [/]\n"
        "[dim]     █████████     [/]\n"
        "[yellow]★[/]    [blue]███████[/]    [yellow]★[/]\n"
        "[blue] ██  ███████  ██ [/]\n"
        "[blue]  █  ███████  █  [/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]    ███████████    [/]\n"
        "[blue]     █████████     [/]\n"
        "[blue]      ███████      [/]\n"
        "[blue]       ▀▀▀▀▀       [/]\n"
        "                     \n"
        "                     "
    ),
    (
        "[yellow]         ▄         [/]\n"
        "[yellow]        ███        [/]\n"
        "[yellow]       █████       [/]\n"
        "[yellow]      ███████      [/]\n"
        "[yellow]     █████████     [/]\n"
        "[dim]     █████████     [/]\n"
        "[dim]     ██[/][yellow]█[/][dim]███[/][yellow]█[/][dim]██     [/]\n"
        "[dim]     █████████     [/]\n"
        "[blue]      ███████      [/]\n"
        "[blue]     █████████     [/]\n"
        "[blue]    ███████████[/][yellow]✦✦✦[/]\n"
        "[blue]   █████████████[/][yellow] ✦✦[/]\n"
        "[blue]   █████████████[/][yellow]  ✦[/]\n"
        "[blue]   █████████████   [/]\n"
        "[blue]   ██████ ██████   [/]\n"
        "[blue]   ████     ████   [/]\n"
        "[blue]   ███       ███   [/]\n"
        "[dim]   ▄▄▄       ▄▄▄   [/]\n"
        "[dim]  █████     █████  [/]\n"
        "[dim]  ▀▀▀▀▀     ▀▀▀▀▀  [/]"
    ),
]


class AboutPanel(Widget):
    DEFAULT_CSS = """
    AboutPanel { width: 1fr; height: 1fr; layout: vertical; padding: 1; }
    #about-logo { color: $primary; height: auto; text-style: bold; content-align: center middle; text-align: center; padding: 1 0; }
    #about-info { height: auto; padding: 1 0; }
    #about-clock { text-align: right; color: $success; height: auto; }
    #about-quote { color: $warning; text-style: italic; height: auto; padding: 1 0; border: solid $primary-darken-2; margin: 1 0; }
    #about-ack { height: auto; color: $text-muted; }
    #about-mage { height: 22; content-align: center middle; text-align: center; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._timer: Timer | None = None
        self._mage_frame = 0
        self._tick_count = 0

    def compose(self) -> ComposeResult:
        yield Static(TITLE, id="about-logo")
        yield Static("", id="about-clock")
        yield Static("", id="about-info")
        yield Static("", id="about-quote")
        yield Static("", id="about-ack")
        yield Static(BLACK_MAGE_FRAMES[0], id="about-mage", markup=True)

    def on_mount(self) -> None:
        self._update_info()
        self._update_clock()
        self._timer = self.set_interval(0.5, self._tick)

    def _tick(self) -> None:
        self._tick_count += 1
        if self._tick_count % 2 == 0:
            self._update_clock()
        self._animate_mage()

    def _animate_mage(self) -> None:
        self._mage_frame = (self._mage_frame + 1) % len(BLACK_MAGE_FRAMES)
        with contextlib.suppress(Exception):
            self.query_one("#about-mage", Static).update(BLACK_MAGE_FRAMES[self._mage_frame])

    def _update_clock(self) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with contextlib.suppress(Exception):
            self.query_one("#about-clock", Static).update(f"⏰ {now}")

    def _update_info(self) -> None:
        try:
            import textual

            info = (
                f"[bold]biblio-uplift[/bold] v{biblio_uplift.__version__}\n"
                f"\n"
                f"Author:   Cody Lusk\n"
                f"License:  MIT (internal)\n"
                f"Python:   {platform.python_version()}\n"
                f"Textual:  {textual.__version__}\n"
                f"Platform: {platform.system()} {platform.release()}\n"
                f"Host:     {platform.node()}\n"
            )
            self.query_one("#about-info", Static).update(info)

            quote = random.choice(QUOTES)  # noqa: S311
            self.query_one("#about-quote", Static).update(f"  {quote}")

            ack = (
                "[bold]Acknowledgements[/bold]\n"
                "  Textual (textualize.io) — Terminal UI framework\n"
                "  Click — CLI framework\n"
                "  Pydantic — Config validation\n"
                "  Rich — Terminal formatting\n"
                "  OpenSSH — The backbone of remote ops\n"
                "  Docker — Container runtime\n"
            )
            self.query_one("#about-ack", Static).update(ack)
        except Exception:
            pass
