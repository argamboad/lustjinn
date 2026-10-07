// Pandoc template for the course: pandoc renders the chapters into a .typ file next to this one,
// and typst compiles that into the PDF (see build.ps1). Code is highlighted by Typst itself.
// Dark by default; `-V light=true` gives a printable light version.

// ---- Palette ---------------------------------------------------------------------------------
$if(light)$
#let bg      = rgb("#ffffff")
#let surface = rgb("#f5f2f7")
#let border  = rgb("#e2dce8")
#let ink     = rgb("#1f1a24")
#let muted   = rgb("#6b6375")
#let accent  = rgb("#b23a5b")
$else$
#let bg      = rgb("#14121a")
#let surface = rgb("#1d1a25")
#let border  = rgb("#2e2a38")
#let ink     = rgb("#e7e2ec")
#let muted   = rgb("#9a92a6")
#let accent  = rgb("#ec7f9b")
$endif$
#let callout-colors = (
  dotnet:  rgb("#8b6cf0"),   // .NET purple
  note:    rgb("#4fb3c9"),
  warning: rgb("#e0a24a"),
  try:     rgb("#6cc58a"),
)
#let callout-titles = (
  dotnet:  "The .NET lens",
  note:    "Worth knowing",
  warning: "Watch out",
  try:     "Try it",
)

// ---- Definitions pandoc's Typst writer relies on ---------------------------------------------
#let horizontalRule = line(length: 100%, stroke: 0.5pt + border)
#let divider = horizontalRule

#let callout(kind, body) = block(
  width: 100%,
  inset: (x: 12pt, y: 10pt),
  radius: 4pt,
  fill: surface,
  stroke: (left: 3pt + callout-colors.at(kind)),
  breakable: true,
)[
  #text(size: 0.8em, weight: "bold", fill: callout-colors.at(kind), upper(callout-titles.at(kind)))
  #v(-0.3em)
  #body
]

// ---- Page and text ---------------------------------------------------------------------------
#set document(title: [$title$])
#set page(
  paper: "a4",
  fill: bg,
  margin: (x: 2.2cm, top: 2.4cm, bottom: 2.4cm),
  footer: context {
    if counter(page).get().first() > 1 {
      set text(size: 8pt, fill: muted)
      [$title$]
      h(1fr)
      counter(page).display()
    }
  },
)
#set text(font: ("Segoe UI", "Libertinus Serif"), size: 10.5pt, fill: ink, lang: "$lang$")
#set par(justify: false, leading: 0.75em, spacing: 1.2em)
#show link: set text(fill: accent)

// Chapters start at 0: "Chapter 0 · Orientation", sections "0.1", "0.2"…
#set heading(numbering: (..n) => {
  let parts = n.pos()
  parts.at(0) = parts.at(0) - 1
  parts.map(str).join(".")
})
#show heading: set text(fill: ink, weight: "semibold")
#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  v(2.5cm)
  text(size: 10pt, weight: "bold", fill: accent, tracking: 0.12em)[CHAPTER #counter(heading).display()]
  v(0.2em)
  text(size: 26pt, weight: "semibold", it.body)
  v(1.2em)
}
#show heading.where(level: 2): it => {
  v(1em)
  text(size: 15pt, it)
  v(0.3em)
}
#show heading.where(level: 3): set text(size: 12pt, fill: accent)

// ---- Code ------------------------------------------------------------------------------------
$if(light)$
$else$
#set raw(theme: "code-dark.tmTheme")
$endif$
// No ligatures: a learner should see `->` and `!=` as typed, not as arrows and symbols.
#show raw: set text(
  font: ("Cascadia Code", "Cascadia Mono", "DejaVu Sans Mono"),
  size: 9pt,
  ligatures: false,
  features: (calt: 0),
)
#show raw.where(block: false): it => box(
  fill: surface, inset: (x: 2pt), outset: (y: 3pt), radius: 2pt, it,
)
// Blocks a little smaller than inline code, so a 100-character line (ruff's limit) fits the page.
#show raw.where(block: true): set text(size: 7.8pt)
#show raw.where(block: true): it => block(
  width: 100%, fill: surface, inset: (x: 8pt, y: 9pt), radius: 4pt, stroke: 0.5pt + border, it,
)

// ---- Tables ----------------------------------------------------------------------------------
#set table(
  inset: (x: 8pt, y: 6pt),
  stroke: (x, y) => (bottom: 0.5pt + border),
  fill: (x, y) => if y == 0 { surface },
)
#show table.cell.where(y: 0): set text(weight: "semibold", fill: accent)
#show figure.where(kind: table): set block(breakable: true)
#show table.cell: set align(left)

// ---- Title page ------------------------------------------------------------------------------
#page(footer: none)[
  #v(1fr)
  // The logo, as the app's own tile: the robot genie rising from the lamp, cream and gold on
  // navy, which is the one square that reads the same on the dark and the light edition.
  #box(clip: true, radius: 18pt, image("/brand/logo.svg", width: 4.2cm))
  #v(1.2em)
  #text(size: 48pt, weight: "bold", fill: accent)[$title$]
  #v(0.2em)
  #text(size: 16pt, fill: ink)[$subtitle$]
  #v(2em)
  #line(length: 30%, stroke: 1pt + accent)
  #v(1em)
  #text(size: 9.5pt, fill: muted)[
    A course that grows with the code. This edition was built on $date$.
  ]
  #v(2fr)
]

$if(toc)$
#v(2.5cm)
#text(size: 26pt, weight: "semibold")[Contents]
#v(1.2em)
#{
  show outline.entry.where(level: 1): set text(weight: "semibold")
  outline(title: none, depth: $toc-depth$)
}
$endif$

$body$
