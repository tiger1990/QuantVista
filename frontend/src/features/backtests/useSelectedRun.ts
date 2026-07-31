"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** The run being viewed lives in the URL, not React state: component state is lost on refresh, so
 * a finished tearsheet would vanish and force a re-run. As a search param it also makes a run
 * linkable and lets the history list open any past run. */
export const RUN_PARAM = "run";

export function useSelectedRun(): [string | null, (id: string | null) => void] {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  const select = useCallback(
    (id: string | null): void => {
      const next = new URLSearchParams(params.toString());
      if (id) next.set(RUN_PARAM, id);
      else next.delete(RUN_PARAM);
      const qs = next.toString();
      // `replace` (not `push`): selecting runs shouldn't stack history entries to back out of.
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  return [params.get(RUN_PARAM), select];
}
