# The course

`lustjinn-course.pdf` teaches Python as a backend by following this app as it is built, mapped to
.NET. One chapter per roadmap step (see `../KICKOFF.md`), in `chapters/`, ordered by file name.

## Keeping it up to date

A step is not done until its chapter is. A change that teaches something — a new tool, library,
pattern or decision — updates its chapter **and rebuilds the PDF in the same commit**. When the
chapter and the code disagree, the chapter is the bug.

## Building

Needs **pandoc** and **Typst** on `PATH` (`winget install JohnMacFarlane.Pandoc Typst.Typst`).

```powershell
./docs/course/build.ps1          # lustjinn-course.pdf — dark, committed
./docs/course/build.ps1 -Light   # lustjinn-course-light.pdf — for printing, not committed
```

| File | Role |
|---|---|
| `chapters/*.md` | The text, in pandoc Markdown |
| `metadata.yaml` | Title, subtitle, contents depth |
| `template.typ` | The design: palette, title page, headings, code, tables, boxes |
| `callouts.lua` | Turns `::: dotnet`, `::: note`, `::: warning`, `::: try` into boxes |
| `code-dark.tmTheme` | Code colours for the dark edition |
