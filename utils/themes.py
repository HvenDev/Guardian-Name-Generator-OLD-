from dataclasses import dataclass
from rich.text import Text


@dataclass
class Theme:
    name: str
    primary: str
    secondary: str
    accent: str
    success: str
    warning: str
    error: str
    unknown: str
    muted: str
    info: str
    panel_border: str
    menu_hotkey: str
    menu_desc: str


THEMES = {
    "Purple Neon": Theme(
        name="Purple Neon",
        primary="bold magenta",
        secondary="purple",
        accent="bold bright_magenta",
        success="bold green",
        warning="bold yellow",
        error="bold red",
        unknown="dim",
        muted="dim purple",
        info="bold cyan",
        panel_border="magenta",
        menu_hotkey="bold magenta",
        menu_desc="white",
    ),
}

DEFAULT_THEME = "Purple Neon"

THEME_NAMES = list(THEMES.keys())


def get_theme(name=None) -> Theme:
    if isinstance(name, str) and name in THEMES:
        return THEMES[name]
    return THEMES[DEFAULT_THEME]
