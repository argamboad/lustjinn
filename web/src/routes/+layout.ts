// A static, single-page app: every route renders in the browser, and the static adapter serves
// index.html for any path (the `fallback` in vite.config.ts), so /story/<id> opens on a reload.
export const ssr = false;
export const prerender = false;
