"""The one theme: airp's Dark palette as a Textual theme.

The terminal client is dark by design, like a real terminal app: one theme, no switch. Every
colour the views use is a *role* defined here, reached as a theme variable (``$muted`` in TCSS,
``[$muted]`` in content markup); no widget names a colour of its own.

Roles, with the donor's Spectre names (``Ui/Theme.cs``, the Dark palette):
  text        Grey85      what is read — Textual's ``foreground``
  muted       Grey50      what is secondary: labels, ages, hints
  heading     SkyBlue1    bold titles — Textual's ``primary``
  accent      Aquamarine1 the reader's own things, key caps, the selection marker
  success     SpringGreen2  the character's name, good news
  warning     Orange1     costs, pending work, scenes
  error       Red1        refusals, failures
  border      Grey35      rules and hairlines
  surface     Grey19      a tinted background: chips, key caps, the list pane
  selection   Black on SkyBlue1, bold
  highlight   Black on Yellow — a search match
  badge       Black on SpringGreen2, bold — the server badge in the masthead
  action      muted + italic — narration between asterisks (derived, ``ACTION``)
  key         accent on surface — a key cap (derived, ``KEY``)
"""

from __future__ import annotations

from typing import Final

from textual.theme import Theme

NAME: Final = "lustjinn"

DARK: Final = Theme(
    name=NAME,
    primary="#87d7ff",  # heading
    secondary="#5fffd7",
    accent="#5fffd7",
    foreground="#dadada",  # text
    background="#0a0d1b",  # the brand's navy; airp drew on the terminal's own ground
    surface="#303030",
    panel="#1c1f2e",
    boost="#ffffff08",
    warning="#ffaf00",
    error="#ff0000",
    success="#00d787",
    dark=True,
    variables={
        "muted": "#808080",
        "border": "#585858",
        "selection-fg": "#000000",
        "selection-bg": "#87d7ff",
        "highlight-fg": "#000000",
        "highlight-bg": "#ffff00",
        "badge-fg": "#000000",
        "badge-bg": "#00d787",
        "diff-added": "#00af5f",
        "diff-removed": "#af5f5f",
    },
)

# Markup openers for the derived roles: a view writes f"{KEY} Enter [/]" and never a colour.
KEY: Final = "[$accent on $surface]"
ACTION: Final = "[italic $muted]"
HEADING: Final = "[bold $primary]"
SELECTION: Final = "[bold $selection-fg on $selection-bg]"
HIGHLIGHT: Final = "[$highlight-fg on $highlight-bg]"
BADGE: Final = "[bold $badge-fg on $badge-bg]"
