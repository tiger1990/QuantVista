"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

/**
 * App-wide client providers. Server state is owned by TanStack Query (per the
 * project's state-management split). MUI's ThemeProvider + Recharts are wired in
 * with the design-system story (QV-034); the packages are installed and ready.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
