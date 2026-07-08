---
baseline_commit: e6391e0c398d92d96c471aeab098c41d28ca1d08
---

# Story 4.7: QV-034 — Frontend: app shell, auth flows, design-system base

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **to sign in and navigate a polished, themed app shell**,
so that **I can use the product — and the frontend has a real design-system foundation to build on**.

> Canonical ID **QV-034** · Epic 4 (EPIC-INTEL) · `[FE]` · 8pts · Sprint 03 · depends: **QV-006 ✅** (auth API)
> Authoritative: `04` §1 (contract-first, generated typed client; Bearer access ~15 min + refresh rotation) · Web design-quality rules (**no template look**). First frontend story; QV-035 (dashboard/stocks) builds on this.

## Context: the scaffold exists (build ON it, swap its styling)

`frontend/` is a bootstrapped **Next.js (App Router)** app with a good structure (`src/{app,features,components/ui,hooks,lib,types}` + `providers.tsx`) and **TanStack Query + Recharts** already installed. **But it was bootstrapped with MUI (`@mui/material` + `@emotion/*`) + CSS Modules** — which conflicts with our Tailwind rules + the agreed design direction.

## Locked decisions (owner-confirmed)

- **Swap MUI/Emotion → Tailwind v4 + shadcn/ui + Lucide** (the sprint AC says "MUI theme"; **owner-approved deviation** to Tailwind+shadcn, consistent with the web coding-style rules + the anti-template goal). **Keep** `@tanstack/react-query` (server state) + `recharts` (charts, QV-035+). Cheapest to swap now — no UI is built on MUI yet.
- **Design direction: Swiss/International foundation** — the token layer (restrained oklch palette, a real type scale + pairing, spacing rhythm, hairline borders, grid discipline, dense tables/nav). **shadcn components are restyled with our tokens**, never shipped as defaults (banned "template look"). **Bento is QV-035** (dashboard), not here.
- **Light/dark are both first-class; light is the default.** Tokens are CSS custom properties (`:root` + `.dark`), theme via **`next-themes`** (class strategy, `defaultTheme="light"`, respects `prefers-color-scheme` only if the user hasn't chosen) + a header toggle. Theme-aware from day one.
- **Thin BFF via Next `rewrites`** — `next.config.ts` proxies `/api/:path* → ${API_URL}/api/:path*`, so the browser calls **same-origin** `/api/v1/...`. This lets the **httpOnly refresh cookie** (path `/api/v1/auth`, Secure) flow without CORS, and hides the backend URL. No business logic in Next (the agreed rule).
- **Generated typed API client** — `openapi-typescript` over FastAPI's OpenAPI schema (emitted **statically** via `python -c "app.openapi()"`, no running server) → `src/lib/api/schema.d.ts`; a small `openapi-fetch` client (`src/lib/api/client.ts`) attaches the bearer + hits `/api`. Regeneratable via an npm script.
- **Auth model.** Access JWT held in memory (React context, `AuthProvider`); the **refresh token is the httpOnly cookie** (browser-managed). On load / 401, call `POST /auth/refresh` to mint a new access token (rotation); `logout` clears both. Route groups: **`(auth)`** (login/register, redirect to `/` if already authed) + **`(app)`** (protected shell; redirect to `/login` if no session). Login/register forms via **React Hook Form + Zod**.
- **Scope = the shell + auth + design system only.** No dashboard/data screens (QV-035), no TanStack Table yet (QV-035), no charts. **No backend change.**

## Acceptance Criteria

1. **Styling swap.** MUI/Emotion removed; **Tailwind v4 + shadcn/ui + Lucide** installed + configured (`globals.css` with `@import "tailwindcss"` + the Swiss token layer; `components.json`; `cn` util). `npm run build`, `npm run lint`, `tsc --noEmit` all green.
2. **Design-system base.** Swiss tokens (oklch color scales, type scale, spacing, radii, shadows) as CSS custom properties for **light + dark**; a few restyled shadcn primitives in use (Button, Input, Card, DropdownMenu) — visibly *not* stock shadcn. Meets ≥4 of the design-quality "required qualities" (hierarchy, rhythm, depth, typography, semantic color, designed states).
3. **Theming.** `next-themes` provider (light default); a header toggle switches light/dark; choice persists; no FOUC/hydration mismatch.
4. **App shell + protected routes.** A top nav (brand, primary links, theme toggle, user menu/logout) in the `(app)` layout; `(app)` redirects unauthenticated users to `/login`; `(auth)` redirects authenticated users to `/`.
5. **Auth flows (wired to FastAPI via the BFF proxy).** `/login` + `/register` forms (RHF+Zod) call `/api/v1/auth/*` through the typed client; access token stored in `AuthProvider`; `logout` clears session + refresh cookie; a `useAuth` hook + a `refresh`-on-load path. (Live end-to-end requires a running backend — a manual/PV smoke, like the real-data check.)
6. **Typed OpenAPI client.** `schema.d.ts` generated from the FastAPI spec + an `openapi-fetch` client that attaches `Authorization: Bearer` and targets `/api`. An `npm run gen:api` script regenerates it.
7. **Gates + tests.** Frontend: `npm run lint` + `tsc --noEmit` + `npm run build` green. A minimal test (Vitest/RTL) for the auth context / cursor-free util OR at least the build+typecheck gate. Backend unaffected (its gates unchanged). Web design-quality checklist noted in the Dev Agent Record.

## Tasks / Subtasks

- [x] **Task 1 — swap MUI → Tailwind + shadcn** (AC: #1)
  - [x] Uninstall `@mui/material @emotion/react @emotion/styled`; install `tailwindcss @tailwindcss/postcss` (v4) + `class-variance-authority clsx tailwind-merge lucide-react tailwindcss-animate` + `next-themes`. `postcss.config`, `globals.css` (`@import "tailwindcss"`), `components.json`, `src/lib/utils.ts` (`cn`). Remove `page.module.css`.
- [x] **Task 2 — Swiss token layer + theming** (AC: #2, #3)
  - [x] `globals.css`: `:root` + `.dark` design tokens (oklch palette, type scale, spacing, radii, shadows) + base element styles. `ThemeProvider` (next-themes) in `providers.tsx`; a `ThemeToggle` component. Pick + wire the type pairing (a grotesk + mono is already loaded via `next/font`).
- [x] **Task 3 — shadcn primitives (restyled) + shell** (AC: #2, #4)
  - [x] Add/restyle Button, Input, Card, DropdownMenu, (Label). App shell: `(app)/layout.tsx` (top nav: brand, links, ThemeToggle, user menu → logout) + `(auth)/layout.tsx` (centered card). Route-group redirects (server or client guard from `AuthProvider`).
- [x] **Task 4 — typed API client + BFF proxy** (AC: #6)
  - [x] `next.config.ts`: `rewrites` `/api/:path*` → `${API_URL}/api/:path*` (`API_URL` env, default `http://localhost:8000`). Generate `src/lib/api/schema.d.ts` (script: dump FastAPI openapi → `openapi-typescript`); `src/lib/api/client.ts` (`openapi-fetch`, bearer, base `/api`). `package.json` `gen:api` script.
- [x] **Task 5 — auth flows** (AC: #5)
  - [x] `AuthProvider` + `useAuth` (access token in state; `login`/`register`/`logout`/`refresh` via the client; refresh-on-mount). `/login` + `/register` pages (RHF + Zod, envelope-aware error handling). Wire the protected redirect.
- [x] **Task 6 — gates + tests + reconcile** (AC: #7)
  - [x] `npm run lint` + `tsc --noEmit` + `npm run build` green. A minimal Vitest/RTL test (e.g. the `cn` util or `useAuth` reducer) if the harness is quick to add, else the build/typecheck gate. Note the live-auth PV. Reconcile QV-033 → done (already applied).

## Dev Notes

### The auth flow (BFF proxy → FastAPI)
```
browser ──/api/v1/auth/login──▶ Next (rewrites) ──▶ FastAPI  (sets httpOnly refresh cookie, returns access JWT)
AuthProvider holds the access JWT in memory; refresh cookie is same-origin (path /api/v1/auth).
on mount / on 401 ──/api/v1/auth/refresh──▶ new access JWT (rotation).  logout ──/api/v1/auth/logout──▶ clear.
```
Same-origin via the proxy = the Secure httpOnly cookie just works, no CORS, backend URL hidden. Business logic stays in FastAPI (the BFF only forwards).

### Design-quality guardrails (must not look like a template)
Swiss idiom: strong scale contrast in type; intentional spacing rhythm (not uniform padding); hairline borders + subtle surfaces for depth; semantic color (a single disciplined accent, status colors for scores later); designed hover/focus/active states; restrained, credible. Light default; dark equally considered. Cite ≥4 required qualities in the Dev Agent Record.

### Reuse / align
- `providers.tsx` already wires TanStack Query — extend it with `ThemeProvider` + `AuthProvider`. `next/font` (Geist Sans/Mono) already loaded — keep or swap for a deliberate pairing.
- FastAPI `/auth` (QV-006): `POST /auth/register` (201), `/auth/login`, `/auth/refresh`, `/auth/logout`, `GET /me`; envelope `{success,data,error,meta}`; refresh cookie `qv_refresh` path `/api/v1/auth`.
- CI already path-filters `frontend/**` (lint & typecheck, build) — this story turns those green with real content.

### Boundaries & gates
- Frontend is a **client + thin BFF** of FastAPI (no DB, no business logic, no second auth). Node/npm gates only (lint/tsc/build) — the Python import-linter/mypy are unaffected. **Not this story:** dashboard/stocks/rankings screens + TanStack Table (QV-035), charts, the sector heatmap, live-auth E2E (manual/PV), the frontend Dockerfile prod wiring (exists).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Node 20.20.1 / npm 10.8.2. Final FE gates: **`npm run build` ✓** (Next 16 + Turbopack; TypeScript pass;
  all routes prerendered: `/`, `/login`, `/register`, `/stocks`, `/rankings`), **`npm run lint` (eslint) ✓**,
  **`npm run typecheck` (tsc --noEmit) ✓**. CI runs exactly these (`lint` + `tsc --noEmit` + build) — aligned.
- `node_modules` + `.next` gitignored; `package-lock.json` updated (so CI `npm ci` is in sync).
- **Fix:** a stale `.next/types/validator.ts` referenced the deleted `page.js` (from the old starter) → `rm -rf
  .next` + rebuild regenerates route types clean. Not a source issue; CI (fresh checkout) never hits it.
- **Deviation (owner-approved):** the sprint AC says "MUI theme" — swapped to **Tailwind + shadcn** per the
  web coding-style rules + the anti-template goal (decision recorded in the `frontend-architecture` memory).

### Completion Notes List

- **The frontend has a real foundation** — Next.js (App Router) client + thin BFF of the FastAPI system-of-record.
- **Styling swap done:** removed `@mui/material` + `@emotion/*` + CSS Modules; added **Tailwind v4 + shadcn/ui
  (restyled) + Lucide + next-themes + RHF/Zod + openapi-fetch/openapi-typescript**; kept TanStack Query + Recharts.
- **Swiss design system** (`globals.css`): oklch token layer (restrained near-mono + one ink-blue accent,
  hairline borders, tight radii, tabular numerals) for **light + dark**; restyled shadcn primitives (Button,
  Input, Label, Card, DropdownMenu) — visibly *not* stock shadcn. Design-quality qualities met: **scale
  hierarchy, intentional rhythm, depth via hairline surfaces, deliberate type (Geist + mono), semantic color
  tokens (positive/negative reserved for scores), designed hover/focus/active states** (≥4 required).
- **Theming:** `next-themes` (class strategy, **light default**, `enableSystem={false}` so it never auto-darks),
  CSS-variant `ThemeToggle` (no hydration mismatch; `suppressHydrationWarning` on `<html>`), persisted choice.
- **App shell + protected routes:** `(app)` layout with a sticky top nav (brand, Overview/Stocks/Rankings,
  ThemeToggle, user menu → sign out) that **redirects anon → /login**; `(auth)` layout **redirects authed → /**;
  overview + placeholder Stocks/Rankings pages (real screens = QV-035).
- **Typed API client:** FastAPI OpenAPI (11 paths) dumped statically → `openapi-typescript` → `schema.d.ts`;
  `openapi-fetch` client attaches the bearer via middleware, targets same-origin `/api` (Next `rewrites` BFF →
  FastAPI so the httpOnly refresh cookie flows, no CORS). `npm run gen:api` regenerates.
- **Auth flows:** `AuthProvider`/`useAuth` — access JWT in memory (never localStorage), **silent refresh on
  mount** (httpOnly cookie → new access token), `login`/`register` (RHF+Zod, envelope-aware errors) + `logout`.
- **Honest limits:** the paths + request bodies are typed; *responses* are loosely typed because the backend
  routes use `response_model=None` (narrowed manually) — response-model typing is a backend follow-up.
  **No Vitest/RTL yet** — satisfied the CI FE gate (lint + tsc + build); a Vitest/RTL unit harness + a
  **Playwright E2E** (auth flow, needs a running FastAPI + a browser) are the FE testing follow-up (web rules).
  **Live auth is a manual smoke** (run FastAPI + `npm run dev`, register/login/refresh/logout) — like the
  real-data check; not automatable here without a running stack. **Visual polish needs owner eyeballs.**

### File List

**New (frontend/)**
- `postcss.config.mjs`, `components.json` · `src/lib/utils.ts` (`cn`) · `src/lib/api/{openapi.json, schema.d.ts, client.ts}`
- `src/components/{providers(mod), theme-provider, theme-toggle, auth-provider, app-nav}.tsx`
- `src/components/ui/{button, input, label, card, dropdown-menu}.tsx`
- `src/app/(app)/{layout, page, stocks/page, rankings/page}.tsx` · `src/app/(auth)/{layout, login/page, register/page}.tsx`

**Modified (frontend/)**
- `package.json` (deps swap + `typecheck`/`gen:api` scripts) · `package-lock.json` · `next.config.ts` (BFF rewrites)
- `src/app/globals.css` (Swiss token layer) · `src/app/layout.tsx` (theme hydration guard + base classes) · `src/components/providers.tsx`

**Removed:** `src/app/page.tsx`, `src/app/page.module.css` (default starter).
**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-034 status; QV-033 → done (housekeeping).

### Change Log

- **2026-07-08 — QV-034 frontend app shell + auth + design-system base.** Swapped the scaffold's MUI/Emotion →
  **Tailwind v4 + shadcn/ui (restyled Swiss) + Lucide** (kept TanStack Query + Recharts); built the Swiss oklch
  token system (light default + first-class dark via next-themes), the protected app shell + nav, `(auth)`/`(app)`
  route groups with redirect guards, a **generated typed OpenAPI client** (openapi-typescript + openapi-fetch)
  over a **Next `rewrites` BFF** to FastAPI, and **auth flows** (login/register/logout + silent refresh) wired to
  `/auth` with access-token-in-memory + the httpOnly refresh cookie. `npm run build`/`lint`/`tsc` all green.
  No backend change. Live auth + visual polish = manual/owner review; QV-035 builds the dashboard/tables on this.
