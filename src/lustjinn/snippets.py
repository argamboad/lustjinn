"""Expanding `:name` into the snippet of that name, in a message that is about to be sent.

A snippet is authored prose deployed at the dramatically right moment: written once, typed as
`:storm`, replaced by its text before the message is stored. The stored text is the expanded
text; the snippet is never read again.

The hard part is not finding a colon but knowing when a colon is *not* a trigger. Prose is
full of them: `10:30`, `https://…`, `note: this`. So a trigger must open a word (preceded by
whitespace or nothing), its name is letters, digits, `_`, `+` and `-` only, and it must not be
closed by another colon — `:name:` is an emoji shortcode, which the clients handle and the API
passes through untouched. Anything else is left exactly as typed: a message is permanent, and
guessing at it is not.
"""

from collections.abc import Callable, Mapping

MAX_NAME_LENGTH = 32
NAME_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-")


def expand(text: str, snippet: Callable[[str], str | None]) -> str:
    """Replaces every `:name` that opens a word and names a snippet with the snippet's text."""
    out: list[str] = []
    i = 0
    while i < len(text):
        opens_word = text[i] == ":" and (i == 0 or text[i - 1].isspace())
        if not opens_word:
            out.append(text[i])
            i += 1
            continue
        end = i + 1
        while end < len(text) and text[end] in NAME_CHARACTERS and end - i <= MAX_NAME_LENGTH:
            end += 1
        name = text[i + 1 : end]
        closed = end < len(text) and text[end] == ":"
        # A run of name characters longer than any name can be is not a name cut short.
        too_long = end < len(text) and text[end] in NAME_CHARACTERS
        if name and not closed and not too_long and (expansion := snippet(name)):
            out.append(expansion)
            i = end
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def by_name(snippets: Mapping[str, str]) -> Callable[[str], str | None]:
    """A lookup over a name-to-text mapping, without regard to case."""
    lowered = {name.lower(): text for name, text in snippets.items()}
    return lambda name: lowered.get(name.lower())
