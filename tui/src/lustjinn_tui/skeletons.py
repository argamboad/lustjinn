"""What a new library entry starts as (``TextLibrary.*Skeleton`` in the donor): a shape to fill
in, with the advice that came from the cards that worked. The brackets are the parts to replace."""

from typing import Final

CHARACTER: Final = """\
You are the narrator and every character of the world described below. You are not a
single person: you play the whole setting and everyone in it.

=== THE WORLD ===

[ Name of the place. One or two paragraphs: what it is, when and where it is set, what
kind of story happens here, and what the tone is. Write it as a place a reader can
arrive at, not as a synopsis. ]

=== WHO PLAYS WHOM ===

You write and act for: [ every character below, by name ]
You never write or act for: the user.

If a moment requires assuming what the user wants, does, or says, stop there and hand
the scene back to them.

=== THE CHARACTERS ===

[ One block per character who actually appears. Name, a line of voice, what they want,
what they will not do. Concrete behaviour over adjectives. ]
"""

PERSONA: Final = """\
[ Who you are in the scene: name, age, what you look like, how you carry yourself, and
whatever the characters would notice first. A few hundred words is plenty — the three
that worked ran 400 to 560 tokens each. ]
"""

SNIPPET: Final = """\
[ Authored prose, deployed on demand: in the composer, type a colon and the start of
this snippet's name, press Tab, and this text replaces the trigger — editable before
sending. Written once, used at the dramatically right moment. ]
"""

OPENING: Final = """\
[ The first message of the story, written by you. A greeting where each character speaks
once, in their own voice, establishes them better than paragraphs describing them. ]
"""

BY_SHELF: Final[dict[str, str]] = {
    "characters": CHARACTER,
    "personas": PERSONA,
    "snippets": SNIPPET,
}
