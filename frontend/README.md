# QuantVista frontend

Next.js (App Router) + TypeScript (strict) + MUI · TanStack Query · Recharts. Organised by
**feature/surface**, not by file type.

## Layout

```
src/
├── app/          # Next.js App Router (routes, layouts)
├── features/     # feature folders (one per surface) — populated from QV-034
├── components/   # shared UI; components/ui/ for primitives
│   └── providers.tsx   # client providers (TanStack Query; MUI theme added in QV-034)
├── lib/          # utilities, generated API client (from FastAPI OpenAPI)
├── hooks/        # use-prefixed hooks
└── types/        # shared types
```

## Commands

```bash
npm install
npm run dev          # local dev server
npm run build        # production build
npm run lint         # ESLint
npx tsc --noEmit     # type-check
```

## Conventions

- Server state via **TanStack Query**; never duplicate it into client stores.
- API types come from a **generated typed client** off the FastAPI OpenAPI schema — never
  hand-written (contract-first). Wired in QV-032+.
- Charts via **Recharts**; UI via **MUI**.
