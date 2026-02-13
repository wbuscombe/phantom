#!/usr/bin/env python3
"""Minimal curses-based TUI app for testing the Terminal Runner.

No external dependencies — uses only the Python standard library.

Features:
- Selectable list with j/k navigation
- Enter to select an item
- / to enter search mode with text input
- q to quit
- Prints "Ready" to stdout when initialised
"""

from __future__ import annotations

import curses
import sys

ITEMS = [
    "Dashboard",
    "Settings",
    "Users",
    "Analytics",
    "Reports",
    "Integrations",
    "Notifications",
    "Security",
    "Billing",
    "Help",
]


def main(stdscr: curses.window) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)

    selected = 0
    search_mode = False
    search_text = ""
    status_msg = ""

    # Signal readiness
    sys.stdout.write("Ready\n")
    sys.stdout.flush()

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Title bar
        title = " Phantom Test TUI "
        pad = "═" * ((width - len(title)) // 2)
        title_line = f"{pad}{title}{pad}"
        if len(title_line) < width:
            title_line += "═"
        stdscr.addnstr(0, 0, title_line[:width], width, curses.color_pair(2))

        # Filter items by search
        if search_text:
            filtered = [
                (i, item) for i, item in enumerate(ITEMS) if search_text.lower() in item.lower()
            ]
        else:
            filtered = list(enumerate(ITEMS))

        # Items list
        for display_idx, (orig_idx, item) in enumerate(filtered):
            row = display_idx + 2
            if row >= height - 3:
                break
            prefix = "▸ " if orig_idx == selected else "  "
            line = f"{prefix}{item}"
            if orig_idx == selected:
                stdscr.addnstr(row, 1, line[: width - 2], width - 2, curses.color_pair(1))
            else:
                stdscr.addnstr(row, 1, line[: width - 2], width - 2)

        # Status bar
        if status_msg:
            stdscr.addnstr(height - 3, 1, status_msg[: width - 2], width - 2, curses.color_pair(3))

        # Search bar
        if search_mode:
            search_line = f"Search: {search_text}█"
            stdscr.addnstr(height - 2, 1, search_line[: width - 2], width - 2)
        else:
            hint = "j/k: navigate  Enter: select  /: search  q: quit"
            stdscr.addnstr(height - 2, 1, hint[: width - 2], width - 2)

        # Bottom border (width - 1 to avoid curses ERR on last cell)
        border = "═" * (width - 1)
        stdscr.addnstr(height - 1, 0, border, width - 1, curses.color_pair(2))

        stdscr.refresh()

        key = stdscr.getch()

        if search_mode:
            if key == 27:  # ESC
                search_mode = False
                search_text = ""
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                search_text = search_text[:-1]
            elif key == ord("\n"):
                search_mode = False
            elif 32 <= key <= 126:
                search_text += chr(key)
        else:
            if key == ord("q"):
                break
            elif key == ord("j") or key == curses.KEY_DOWN:
                selected = min(selected + 1, len(ITEMS) - 1)
            elif key == ord("k") or key == curses.KEY_UP:
                selected = max(selected - 1, 0)
            elif key == ord("\n"):
                status_msg = f"Selected: {ITEMS[selected]}"
            elif key == ord("/"):
                search_mode = True
                search_text = ""
                status_msg = ""


if __name__ == "__main__":
    curses.wrapper(main)
