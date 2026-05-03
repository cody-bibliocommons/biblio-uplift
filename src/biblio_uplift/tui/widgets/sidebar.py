"""Sidebar navigation widget.

Provides a reusable Sidebar component built on Textual's ListView/ListItem/Label.
Uses only single-width ASCII characters to avoid alignment issues across terminals.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

_DEFAULT_PREFIXES: tuple[str, ...] = (
    "[",
    ">",
    "#",
    "=",
    "f",
    "@",
    "|",
    "D",
    "^",
    "~",
    "<",
    "*",
    "+",
    "%",
    "&",
    "!",
)


class Sidebar(Widget):
    """Sidebar navigation using ListView."""

    DEFAULT_CSS = """
    Sidebar {
        dock: left;
        width: 28;
        background: $surface-darken-1;
        border-right: solid $primary;
        padding: 0;
        layout: vertical;
    }

    Sidebar #sidebar-title {
        height: 3;
        content-align: center middle;
        text-align: center;
        color: $primary;
        text-style: bold;
        border-bottom: solid $primary-darken-2;
        padding: 1 0;
    }

    Sidebar ListView {
        height: 1fr;
        background: transparent;
        border: none;
        scrollbar-gutter: stable;
        padding: 1 0;
    }

    Sidebar ListView > ListItem {
        padding: 0 1;
        height: 1;
    }

    Sidebar ListView > ListItem:hover {
        background: $primary 20%;
    }

    Sidebar ListView > ListItem.-highlight {
        background: $primary 40%;
        text-style: bold;
    }

    Sidebar ListView > ListItem.-highlight:hover {
        background: $primary 50%;
    }
    """

    current: reactive[str | None] = reactive(None)

    class Selected(Message):
        """Posted when a sidebar item is selected."""

        def __init__(self, section_id: str) -> None:
            super().__init__()
            self.section_id = section_id

    def __init__(
        self,
        items: list[tuple[str, str]] | None = None,
        *,
        title: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._items: list[tuple[str, str]] = list(items or [])
        self._title = title or ""

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(self._title, id="sidebar-title")
        with ListView(id="sidebar-list"):
            for idx, (section_id, label) in enumerate(self._items):
                prefix = _DEFAULT_PREFIXES[idx % len(_DEFAULT_PREFIXES)]
                yield ListItem(
                    Label(f" {prefix} {label}"),
                    id=f"sidebar-{section_id}",
                )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id: str | None = event.item.id
        if item_id and item_id.startswith("sidebar-"):
            section_id = item_id.removeprefix("sidebar-")
            self.current = section_id
            self.post_message(self.Selected(section_id=section_id))

    def watch_current(self, new_value: str | None) -> None:
        self._apply_highlight(new_value)

    def _apply_highlight(self, section_id: str | None) -> None:
        try:
            list_view = self.query_one("#sidebar-list", ListView)
        except Exception:
            return
        for item in list_view.query(ListItem):
            item_section = (item.id or "").removeprefix("sidebar-")
            if item_section == section_id:
                item.add_class("-highlight")
            else:
                item.remove_class("-highlight")

    def on_mount(self) -> None:
        if self.current is None and self._items:
            self.current = self._items[0][0]
