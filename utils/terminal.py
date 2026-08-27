import os
import sys
import ctypes
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

MAGENTA = "bold magenta"
PURPLE = "purple"
DIM_PURPLE = "dim purple"
BRIGHT_MAGENTA = "bold bright_magenta"
GREEN = "bold green"
RED = "bold red"
DIM = "dim"
WHITE = "bold white"
CYAN = "bold cyan"
YELLOW = "bold yellow"

DIVIDER = "  " + "-" * 44


def _build_logo() -> Text:
    G = [
        "###### ",
        "##     ",
        "## ### ",
        "##  ## ",
        "###### ",
    ]
    U = [
        "##  ## ",
        "##  ## ",
        "##  ## ",
        "##  ## ",
        "###### ",
    ]
    A = [
        " ####  ",
        "##  ## ",
        "###### ",
        "##  ## ",
        "##  ## ",
    ]
    R = [
        "#####  ",
        "##  ## ",
        "#####  ",
        "## ##  ",
        "##  ## ",
    ]
    D = [
        "#####  ",
        "##  ## ",
        "##  ## ",
        "##  ## ",
        "#####  ",
    ]
    I = [
        "###### ",
        "  ##   ",
        "  ##   ",
        "  ##   ",
        "###### ",
    ]
    A2 = [
        " ####  ",
        "##  ## ",
        "###### ",
        "##  ## ",
        "##  ## ",
    ]
    N = [
        "##  ## ",
        "### ## ",
        "###### ",
        "## ### ",
        "##  ## ",
    ]

    letters = [G, U, A, R, D, I, A2, N]
    max_w = max(len(row) for letter in letters for row in letter)

    rows = [""] * 5
    for li, letter in enumerate(letters):
        for row_idx in range(5):
            padded = letter[row_idx].ljust(max_w)
            rows[row_idx] += padded
            if li < len(letters) - 1:
                rows[row_idx] += " "

    height = len(rows)
    width = len(rows[0])

    shadow = [[" "] * (width + 1) for _ in range(height + 1)]
    for y in range(height):
        for x in range(width):
            if rows[y][x] == "#":
                shadow[y + 1][x + 1] = "#"

    front = [[" "] * (width + 1) for _ in range(height + 1)]
    for y in range(height):
        for x in range(width):
            if rows[y][x] == "#":
                front[y][x] = "#"

    result = Text()
    result.append("\n")
    for y in range(height + 1):
        result.append("   ")
        for x in range(width + 1):
            if front[y][x] == "#":
                result.append("\u2588", style="bold magenta")
            elif shadow[y][x] == "#":
                result.append("\u2588", style="dim magenta")
            else:
                result.append(" ")
        result.append("\n")
    return result


_progress_lines = 0
_vt_enabled = False

if os.name == "nt":
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        if kernel32.SetConsoleMode(handle, mode.value | 0x0004):
            _vt_enabled = True
    except Exception:
        pass


def clear():
    if _vt_enabled:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    else:
        os.system("cls" if os.name == "nt" else "clear")


def set_title(title: str):
    if os.name == "nt":
        os.system(f"title {title}")
    else:
        sys.stdout.write(f"\033]0;{title}\007")


def show_banner():
    clear()
    logo = _build_logo()
    console.print(logo, justify="center")
    sub = Text("Discord Username Scanner", style=DIM_PURPLE)
    console.print(sub, justify="center")
    console.print()
    console.print(Text(DIVIDER, style=PURPLE), justify="center")
    console.print()


def show_init_banner():
    clear()
    logo = _build_logo()
    console.print(logo, justify="center")
    sub = Text("Discord Username Scanner", style=DIM_PURPLE)
    console.print(sub, justify="center")


def prompt_input(message: str) -> str:
    label = Text(f"  {message}", style=WHITE)
    console.print(label)
    prompt = Text("  > ", style=MAGENTA)
    return console.input(prompt).strip()


def prompt_choice(message: str, options: list) -> str:
    label = Text(f"  {message}", style=WHITE)
    console.print(label)
    for i, opt in enumerate(options, 1):
        num = Text(f"    {i}. ", style=MAGENTA)
        num.append(opt, style=WHITE)
        console.print(num)
    prompt = Text("  > ", style=MAGENTA)
    while True:
        choice = console.input(prompt).strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        console.print(Text("    Invalid choice", style=DIM))


def prompt_int(message: str, min_val: int = 1, max_val: int = 99999) -> int:
    while True:
        raw = prompt_input(message)
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            console.print(Text(f"    Enter {min_val}-{max_val}", style=DIM))
        except ValueError:
            console.print(Text("    Enter a number", style=DIM))


def show_self_test():
    console.print()
    console.print(Text("  Initializing...", style=DIM))
    console.print()


def show_self_test_step(name: str, passed: bool, reason: str = ""):
    status = Text("  [ok]", style=GREEN) if passed else Text("  [!!]", style=RED)
    label = Text(f" {name}", style=WHITE)
    dots = Text(" " + "." * max(1, 30 - len(name)), style=DIM)
    if passed:
        result = Text(" ok", style=GREEN)
    elif reason:
        result = Text(f" {reason}", style=YELLOW)
    else:
        result = Text(" FAIL", style=RED)
    console.print(Text.assemble(status, label, dots, result))


def show_self_test_done(ready: bool):
    console.print()
    if ready:
        console.print(Text("  Ready.", style=GREEN))
    else:
        console.print(Text("  Continuing without preflight check.", style=YELLOW))
    console.print()


def show_results(checked: int, available: int, taken: int, invalid: int,
                 unknown: int, errors: int, elapsed: float):
    console.print()
    console.print(Text(DIVIDER, style=PURPLE), justify="center")
    console.print()

    header = Text("  RESULTS", style=MAGENTA)
    console.print(header)
    console.print()

    speed = checked / elapsed if elapsed > 0 else 0

    rows = [
        ("CHECKED", f"{checked:,}", WHITE),
        ("AVAILABLE", f"{available:,}", GREEN),
        ("TAKEN", f"{taken:,}", RED),
        ("INVALID", f"{invalid:,}", YELLOW),
        ("UNKNOWN", f"{unknown:,}", DIM),
    ]

    max_label = max(len(r[0]) for r in rows)

    for label, value, color in rows:
        lbl = Text(f"    {label}", style=PURPLE)
        pad = " " * (max_label - len(label) + 4)
        val = Text(f"{pad}{value}", style=color)
        console.print(Text.assemble(lbl, val))

    console.print()
    time_row = Text("    TIME", style=PURPLE)
    time_pad = " " * (max_label - 4 + 4)
    time_val = Text(f"{time_pad}{elapsed:.1f}s", style=CYAN)
    console.print(Text.assemble(time_row, time_val))

    speed_row = Text("    SPEED", style=PURPLE)
    speed_pad = " " * (max_label - 5 + 4)
    speed_val = Text(f"{speed_pad}{speed:,.0f}/s", style=CYAN)
    console.print(Text.assemble(speed_row, speed_val))

    console.print()
    console.print(Text(DIVIDER, style=PURPLE), justify="center")


def show_available_list(usernames: list):
    console.print()
    if not usernames:
        console.print(Text("    No available usernames found.", style=DIM))
        console.print()
        return

    header = Text("  AVAILABLE USERNAMES", style=BRIGHT_MAGENTA)
    console.print(header)
    console.print()

    for name in usernames[:50]:
        marker = Text("    > ", style=MAGENTA)
        uname = Text(name, style=GREEN)
        console.print(Text.assemble(marker, uname))

    if len(usernames) > 50:
        console.print(Text(f"    ... and {len(usernames) - 50} more", style=DIM))

    console.print()


_progress_lines = 0


def show_progress(current: str, checked: int, total: int, available: int,
                  taken: int, unknown: int, errors: int, elapsed: float):
    global _progress_lines
    speed = checked / elapsed if elapsed > 0 else 0
    pct = (checked / total * 100) if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * checked / total) if total > 0 else 0
    filled_str = "#" * filled
    empty_str = "." * (bar_len - filled)

    if _progress_lines > 0:
        sys.stdout.write(f"\033[{_progress_lines}A")
        sys.stdout.flush()

    lines = []

    lines.append(f"\r{'':>80}")
    lines.append(f"\r  SCANNING DISCORD".center(80))
    lines.append(f"\r{'':>80}")
    lines.append(f"\r  {DIVIDER}".center(80))
    lines.append(f"\r{'':>80}")
    bar_str = f"    {'#' * filled}{'.' * (bar_len - filled)}  {pct:.0f}%"
    lines.append(f"\r{bar_str:>80}")
    lines.append(f"\r{'':>80}")

    max_label = 9

    def row(label, value):
        pad = " " * (max_label - len(label) + 4)
        return f"    {label}{pad}{value}"

    lines.append(f"\r{row('CHECKED', f'{checked:,} / {total:,}'):>80}")
    lines.append(f"\r{row('AVAILABLE', f'{available:,}'):>80}")
    lines.append(f"\r{row('TAKEN', f'{taken:,}'):>80}")
    lines.append(f"\r{row('INVALID', f'{unknown:,}'):>80}")
    if errors:
        lines.append(f"\r{row('ERRORS', f'{errors:,}'):>80}")
    lines.append(f"\r{row('SPEED', f'{speed:,.0f}/s'):>80}")
    lines.append(f"\r{row('ELAPSED', f'{elapsed:.1f}s'):>80}")
    lines.append(f"\r{'':>80}")
    lines.append(f"\r  {DIVIDER}".center(80))
    lines.append(f"\r{'':>80}")
    lines.append(f"\r    Press CTRL+C to stop".center(80))

    _progress_lines = len(lines)
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def show_error(message: str):
    console.print()
    header = Text("  ERROR", style=RED)
    console.print(header)
    msg = Text(f"    {message}", style=RED)
    console.print(msg)
    console.print()


def show_success(message: str):
    console.print()
    header = Text("  SUCCESS", style=GREEN)
    console.print(header)
    msg = Text(f"    {message}", style=GREEN)
    console.print(msg)
    console.print()


def press_enter():
    console.input(Text("  Press Enter to continue...", style=DIM))
