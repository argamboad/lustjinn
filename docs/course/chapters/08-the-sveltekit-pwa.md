# The SvelteKit PWA

Seven chapters of backend, and not one screen. This chapter is the first client: a web app you
install on a phone, built with **SvelteKit 5**, served as static files, talking to the API over
HTTPS and nothing else. It is also the first chapter where the owner approved a design before a
line of it was built, and will approve the screens again before the step closes — the rule is
written on GitHub #75, and it held.

The step shipped as two pull requests: the shell, sign-in and the two core screens; then the
dials and meters, the composer's helpers, the library editor, the Render site and this chapter.

## Why Svelte, and why static

The kickoff chose SvelteKit over React because a static export of Svelte is close to plain HTML
with a small runtime, and the app had to be light on a phone. Two decisions followed from it:

- **Static, as a single-page app.** `adapter-static` writes `build/` with one `index.html` that
  answers every path (`fallback: 'index.html'`), and the root layout turns server rendering off:

  ```ts
  // src/routes/+layout.ts
  export const ssr = false;
  export const prerender = false;
  ```

  So `/story/<id>` opens on a reload, there is no Node server to host, and the site can live on
  Render's static tier, which never sleeps.
- **Svelte 5 runes from the first line.** `$state`, `$derived`, `$effect`, `$props`. The project
  forces runes mode in `vite.config.ts` so a Svelte 4 example pasted in fails loudly rather than
  working by accident — most of what is online is still Svelte 4.

::: dotnet
If Blazor is the nearest thing you know: a `.svelte` file is a Razor component — markup, a script
block, scoped styles — but it compiles to a small amount of JavaScript at build time; there is no
runtime diffing a virtual DOM and no WebAssembly download. `$state` is a property that notifies
on set, `$derived` a computed property with its dependencies tracked for you, `$effect` what you
would put in `OnParametersSet`. Routes are files: `src/routes/story/[id]/+page.svelte` is
`@page "/story/{id}"`.
:::

## The shell: tokens, theme, and a client

### Tokens in one stylesheet

Everything the owner approved on the design page became `web/src/lib/theme.css`: the navy
ground, the cream ink, the gold that means *you*, and every derived surface and line — defined
once for the dark theme on `:root`, again for light under `prefers-color-scheme: light`, and
again under `[data-theme='light']` so a choice beats the system. No component names a colour of
its own; it says `var(--gold-text)`, and the theme decides what that is.

The theme store is a class with one rune field:

```ts
class Theme {
	mode = $state<ThemeMode>(remembered());
	set(mode: ThemeMode) {
		this.mode = mode;
		if (mode === 'system') delete document.documentElement.dataset.theme;
		else document.documentElement.dataset.theme = mode;
		localStorage.setItem(KEY, mode); // in a try: a private window has no storage
	}
}
export const theme = new Theme();
```

A `.svelte.ts` file may use runes outside a component, which is how one store serves every
screen. One more line matters: `app.html` carries a tiny inline script that applies the
remembered choice *before* the first paint, so a light-theme reader never sees a navy flash.

::: dotnet
A module that exports `new Theme()` is a singleton service registered once; the screens import
it instead of injecting it. `localStorage` is per-origin browser storage, the nearest thing to
`ApplicationData.LocalSettings`, and it can be absent or throw, hence every read in a `try`.
:::

### The API, typed, and a stream read by hand

`web/src/lib/api.ts` is the one place the API's shapes are spelled out in TypeScript —
`Story`, `Message`, `Done`, `Dial`, `Tracker` — and the one place the bearer token is attached.
A refusal becomes an `ApiError` with the API's own sentence; a server that cannot be reached
becomes `Unreachable`, which is a different thing to the screens.

The turn is the interesting call. The API streams a reply as server-sent events, and the
browser's `EventSource` only does GET; a turn is a POST. So the body is read as it arrives and
cut into events by hand:

```ts
export class SseParser {
	private buffer = '';
	push(chunk: string): SseEvent[] {
		this.buffer += chunk.replace(/\r\n/g, '\n');
		const events: SseEvent[] = [];
		let at: number;
		while ((at = this.buffer.indexOf('\n\n')) >= 0) {
			const block = this.buffer.slice(0, at);
			this.buffer = this.buffer.slice(at + 2);
			const parsed = parseBlock(block);
			if (parsed) events.push(parsed);
		}
		return events;
	}
}
```

A chunk may end mid-line, so the tail is kept between calls; the parser is pure and
unit-tested with awkward chunking, CRLF line endings and keep-alive comments. `api.send` feeds
each `delta` to a callback and resolves with the `done` or `error` event, typed as a union the
screen switches on.

::: dotnet
`SseParser` is what you would write around a `StreamReader` if `HttpClient` gave you the response
body as it arrived — which it does, with `HttpCompletionOption.ResponseHeadersRead`. The `Done`
union is a discriminated union on `kind`, the TypeScript way of saying `OneOf<Turn, Aside,
Said, Error>`; `switch (done.kind)` narrows the type in each case.
:::

### The service worker, and a lesson

An installable app needs a manifest and a service worker. The worker caches the built files on
install, so the installed app opens instantly offline to its shell; API calls never pass through
it. SvelteKit 3 wants the worker in its own folder with its own `tsconfig.json` extending
`$app/tsconfig/service-worker`, and gives it `immutable` and `assets` from `$app/manifest`.

The lesson cost an hour: the worker was being registered in the dev server too, and after the
dev server restarted it kept serving a cached shell and answering `503 Offline` for modules that
had moved. The layout now registers it itself, and only in a production build:

```ts
if (!dev && 'serviceWorker' in navigator) {
	void navigator.serviceWorker.register('/service-worker.js', { type: 'module' });
}
```

::: warning
A file whose name contains `.server.` is server-only to SvelteKit — it refuses to bundle it for
the browser "as this could leak sensitive information". The store that knocks on `/health` was
first called `server.svelte.ts` and the whole app went blank with a clear error in the dev
server's log. It is `health.svelte.ts` now.
:::

### Icons from the logo

`web/scripts/icons.mjs` renders the manifest icons, a maskable one with the safe zone respected,
the Apple touch icon and a favicon from `brand/logo.svg`, with `sharp` as a dev dependency; the
outputs are committed so a build needs no rasteriser. The same tile is the header's mark, the
lamp on the waking screen, and the cover of this book.

## The gate: waking, then signing in

The root layout renders exactly one of three things:

```svelte
{#if server.state !== 'up'}
	<Waking />
{:else if !session.signedIn}
	<SignIn />
{:else}
	{@render children()}
{/if}
```

The static site opens instantly; the API on Render's free tier sleeps and takes up to a minute to
wake. So the first thing the app does is knock on `/health`, and show the lamp breathing until
something answers — with the wait growing from two to six seconds, and after two minutes a
plainer message and a *try again now*. Sign-in exchanges the name and password for a token the
device keeps for a month. A `401` anywhere sends the reader back to the sign-in screen with a note
saying why; a call that cannot reach the server sends them back to the lamp. The two stores
learn about this through two hooks the API client exposes (`whenSignedOut`, `whenUnreachable`),
which keeps `api.ts` free of imports from the stores that import it.

## The two screens the feel lives in

### The stories

Newest first, the character's initial, the last line in the book face, the month's spend in the
bar from `GET /spend`. A card swiped left shows *Branch* and *Delete*; the swipe is a few
pointer events and a `transform`, and a tap on a swiped card closes it rather than opening the
story. Pull down at the top to refresh. The gold button starts a new story: pick a character, a
persona (the default preselected), a name.

The search box filters with the donor's fuzzy matcher over the story's name, best match first —
the same matcher the terminal uses, ported line for line to `fuzzy.ts` (#135). It first matched
substrings of the name, the character and the preview, so the same letters ordered different
stories in the two clients. A port drifts unless something holds it, so the web's tests include
a table of scores computed by the terminal's `fuzzy.py`, and both must agree to the point. Two
details make that possible: the port counts code points with `Array.from(text)`, not UTF-16
units, so an emoji in a name costs one character in both languages, and the integer mean of a
multi-word query floors as Python's `//` does.

### The conversation

The screen you live in. Your turns are gold-edged on the right; the character's are on the
left as **runs** — the donor's `ProseFormat` rules ported to `prose.ts` and unit-tested: `*action*`
dimmed and italic, `**emphasis**` in gold, `"dialogue"` upright, a star beside whitespace left
as a star, a quote that never closes left as a quote. The reply streams in with a gold caret;
the reader's message appears before the API confirms it.

Everything the composer does is in one component. A leading `/` opens the command palette from
`GET /commands` — a new endpoint, so neither client keeps a copy of the list the API enforces —
with what each command costs; Tab completes. A `:name` at a word start opens the picker: the
library's snippets by name, inserted as their text, and emoji by name or keyword from the
donor's table of 225. `:wave:` becomes 👋 before the message is sent; a bare `:storm` is a
snippet trigger the API expands when it stores the message, as chapter 4 built. Enter sends;
when the composer is empty the send button reads *Carry on ›*.

The emoji table was first ported twice, once into each client, and two copies of a table are
two places to forget an emoji. It is now data in the API's package, `emoji.json` beside
`dials.json`, served as `GET /emoji` (#132): the one route besides `/health` and sign-in that
answers without a token — it says nothing about anyone's stories — and the one response a
browser may cache, for a day. Each client reads it once per session; until then a `:name:` stays
as typed, which is what it would be anyway for a name the table lacks.

Every other response goes out `Cache-Control: no-store`, set by a middleware on the way out.
For `/emoji` to keep its own say, the middleware sets each private header only if the route did
not:

```python
for name, value in PRIVATE.items():
    response.headers.setdefault(name, value)
```

::: dotnet
The middleware is `app.Use(async (ctx, next) => { ctx.Response.OnStarting(...); await next(); })`
adding headers, and `setdefault` is `TryAdd` on `IHeaderDictionary` where `update` was the
indexer: the route's own `Cache-Control`, like `[ResponseCache(Duration = 86400)]`, now wins.
A test asserts that `/health` still goes out `no-store`, so the exception stays one route wide.
:::

Answers that are shown once and stored nowhere — `/ask`, `/recap`, a `/tracker` set — appear as
dashed notes in the conversation, labelled so. Reroll opens a sheet of the nine
reasons; a long press on any turn opens *branch from here*, *cut the story back to here* (with
the count of turns it would hide) and *copy*.

### Beside it: dials, meters, the prompt

The approved design had a third column on the desktop and a ◐ sheet on the phone. Both render
the same component, `StoryRail`, over the same store, `Extras`: the dials in force as controls
(five steps for a scale with the level's exact text under it, a switch, options, items, a
line), the meters with their bars and deltas (set by hand, remove, add), and the newest reply's
audit line read back into bars — `character 2,360 · world 417 …` — beside the story's running
cost with rerolled spend apart. A strip of meter pills rides above the composer. After each
turn the store refreshes, so a meter moves the moment the reply ends.

::: dotnet
`Extras` is a view model: `$state` fields the view binds to, methods that call the API and
update them. `StoryRail` renders it twice — in the column and in the sheet — with
`bind:section` so both show the same tab, which is a two-way binding to a prop, Svelte's
`@bind-Value`.
:::

## The library editor

Three shelves as tabs, the default persona marked and settable from the list, hidden entries on
request. The editor saves with the version it opened, and when the API answers `409` because a
save landed in between, it shows their text under yours with *Replace it with mine* or *Take
theirs* — nothing is lost either way, which is the whole point of chapter 4's version column.
Every saved version is a sheet away and any of them can be put back in the editor.

## Deploying a static site

`render.yaml` gained a second service: a static site built from `web/`, every path rewritten to
`index.html`, `noindex` and `no-referrer` headers, the service worker never cached, and the
commit written to `/version.txt` by the build command. The API's URL is baked in at build time
from `VITE_API_URL`; the API's `LUSTJINN_CORS_ORIGINS` must name the site. That is a two-step
dance done once in Render's dashboard, written down in `docs/DEPLOYMENT.md`. CI's deploy input
gained `web-staging` and `both`; the web deploy job fires the hook and waits until the site
reports the commit. Nothing was triggered: the cloud comes when the owner says so.

## Testing a client

The gates in CI's `web` job: `prettier --check`, `svelte-check` (TypeScript across `.svelte`
files too), `vitest`, and the build itself. The unit tests cover the pure modules — the SSE
parser, the prose runs, the shortcode scanner, the audit line — because that is where a wrong
rule hides; the screens were checked by hand against the running API, with a dev token minted
from the settings and put in `localStorage`. Two things learned the hard way: `#lib/*` imports
in `.svelte` files carry their `.ts` extension, or svelte-check cannot find them; and a prop
cannot be called `state` in a runes file, since `$state` is the rune.

::: try
Run the API and the web app side by side — `uv run uvicorn lustjinn.main:app` and, in `web/`,
`npm run dev` — with `LUSTJINN_CORS_ORIGINS=["http://localhost:5173"]` in `.env`. Open
http://localhost:5173, sign in, and play a turn on the dummy. Then switch the theme on the *You*
screen, open the dials with ◐, set Lust to Explicit and watch the next reply's audit line gain a
`directives` layer in the rail. On a phone on the same network, `npm run dev -- --host` and
*Add to Home Screen*.
:::

## What step 8 leaves behind

- A web app in `web/`: installable, dark and light, phone and desktop, every screen the API has
  a feature for, approved by the owner before and after it was built.
- A pattern for a client: one typed API module, stores as classes with runes, a component per
  screen with scoped styles, pure logic in `.ts` files with tests.
- A second Render service described and documented, not yet deployed.

**Next — Chapter 9, The terminal client.** The same stories in a terminal, with Textual: the
look and feel of airp's console client, dark by design, against the same API.
