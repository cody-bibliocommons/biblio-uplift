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

TITLE = (
    "[bold cyan]╔══════════════════════════════════════════╗[/]\n"
    "[bold cyan]║[/]  [bold white]██████  ██ ██████  ██      ██  ██████[/]   [bold cyan]║[/]\n"
    "[bold cyan]║[/]  [bold white]██   █  ██ ██   █  ██      ██  ██   █[/]   [bold cyan]║[/]\n"
    "[bold cyan]║[/]  [bold white]██████  ██ ██████  ██      ██  ██   █[/]   [bold cyan]║[/]\n"
    "[bold cyan]║[/]  [bold white]██   █  ██ ██   █  ██      ██  ██   █[/]   [bold cyan]║[/]\n"
    "[bold cyan]║[/]  [bold white]██████  ██ ██████  ██████  ██  ██████[/]   [bold cyan]║[/]\n"
    "[bold cyan]║[/]                                          [bold cyan]║[/]\n"
    "[bold cyan]║[/]             [bold yellow]U  P  L  I  F  T[/]             [bold cyan]║[/]\n"
    "[bold cyan]╚══════════════════════════════════════════╝[/]"
)

ROWS = 30
COLS = 80
FAR_STARS = 25
NEAR_STARS = 15
FAR_CHARS = ["·", ".", "⋆"]
NEAR_CHARS = ["✦", "★", "✧", "☆", "*"]


class Starfield:
    """Parallax scrolling starfield with far (dim/slow) and near (bright/fast) layers."""

    def __init__(self):
        # Each star: [row, col, char, is_near]
        self._stars: list[list] = []
        for _ in range(FAR_STARS):
            self._stars.append(
                [
                    random.randint(0, ROWS - 1),  # noqa: S311
                    random.randint(0, COLS - 1),  # noqa: S311
                    random.choice(FAR_CHARS),  # noqa: S311
                    False,
                ]
            )
        for _ in range(NEAR_STARS):
            self._stars.append(
                [
                    random.randint(0, ROWS - 1),  # noqa: S311
                    random.randint(0, COLS - 1),  # noqa: S311
                    random.choice(NEAR_CHARS),  # noqa: S311
                    True,
                ]
            )
        self._tick = 0

    def tick(self) -> None:
        self._tick += 1
        for star in self._stars:
            # Near stars move every tick; far stars move every 2 ticks
            if star[3] or self._tick % 2 == 0:
                star[1] -= 1
            # Wrap around: reappear on right at random row
            if star[1] < 0:
                star[1] = COLS - 1
                star[0] = random.randint(0, ROWS - 1)  # noqa: S311

    def render(self) -> str:
        grid = [[" "] * COLS for _ in range(ROWS)]
        markup = [[None] * COLS for _ in range(ROWS)]
        for star in self._stars:
            r, c = star[0], star[1]
            grid[r][c] = star[2]
            if star[3]:
                markup[r][c] = random.choice(["yellow", "bright_white", "white"])  # noqa: S311
            else:
                markup[r][c] = "dim"
        lines = []
        for r in range(ROWS):
            line = ""
            for c in range(COLS):
                if grid[r][c] == " ":
                    line += " "
                else:
                    line += f"[{markup[r][c]}]{grid[r][c]}[/]"
            lines.append(line)
        return "\n".join(lines)


class AboutPanel(Widget):
    DEFAULT_CSS = """
    AboutPanel { width: 1fr; height: 1fr; layout: vertical; padding: 1; }
    #about-logo { color: $primary; height: auto; content-align: center middle; text-align: center; padding: 0; }
    #about-info { height: auto; padding: 1 0; }
    #about-clock { text-align: right; color: $success; height: auto; }
    #about-quote { color: $warning; text-style: italic; height: auto; padding: 1 0; border: solid $primary-darken-2; margin: 1 0; }
    #about-ack { height: auto; color: $text-muted; }
    #about-stars { height: 1fr; content-align: center middle; overflow: hidden; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._timer: Timer | None = None
        self._starfield = Starfield()
        self._tick_count = 0

    def compose(self) -> ComposeResult:
        yield Static(TITLE, id="about-logo")
        yield Static("", id="about-clock")
        yield Static("", id="about-info")
        yield Static("", id="about-quote")
        yield Static("", id="about-ack")
        yield Static(self._starfield.render(), id="about-stars", markup=True)

    def on_mount(self) -> None:
        self._update_info()
        self._update_clock()
        self._timer = self.set_interval(0.3, self._tick)

    def _tick(self) -> None:
        self._tick_count += 1
        if self._tick_count % 3 == 0:
            self._update_clock()
        self._animate_stars()

    def _animate_stars(self) -> None:
        self._starfield.tick()
        with contextlib.suppress(Exception):
            self.query_one("#about-stars", Static).update(self._starfield.render())

    def _update_clock(self) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with contextlib.suppress(Exception):
            self.query_one("#about-clock", Static).update(f"⏰ {now}")

    def _update_info(self) -> None:
        with contextlib.suppress(Exception):
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
