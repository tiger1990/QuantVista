import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSelectedRun } from "./useSelectedRun";

const replace = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  usePathname: () => "/backtests",
  useRouter: () => ({ replace }),
}));

function Probe() {
  const [selected, select] = useSelectedRun();
  return (
    <div>
      <span data-testid="selected">{selected ?? "none"}</span>
      <button type="button" onClick={() => select("run-9")}>
        open
      </button>
      <button type="button" onClick={() => select(null)}>
        clear
      </button>
    </div>
  );
}

beforeEach(() => {
  replace.mockReset();
  search = "";
});

describe("useSelectedRun", () => {
  it("reads the open run from the URL so a refresh keeps the tearsheet", () => {
    // regression: the run id lived in component state and was lost on reload, forcing a re-run
    search = "run=run-7";
    render(<Probe />);
    expect(screen.getByTestId("selected")).toHaveTextContent("run-7");
  });

  it("is unselected when the URL carries no run", () => {
    render(<Probe />);
    expect(screen.getByTestId("selected")).toHaveTextContent("none");
  });

  it("writes the run to the URL without stacking history entries", () => {
    render(<Probe />);
    screen.getByRole("button", { name: "open" }).click();
    expect(replace).toHaveBeenCalledWith("/backtests?run=run-9", { scroll: false });
  });

  it("preserves other query params when selecting", () => {
    search = "tab=history";
    render(<Probe />);
    screen.getByRole("button", { name: "open" }).click();
    const [url] = replace.mock.calls[0];
    expect(url).toContain("tab=history");
    expect(url).toContain("run=run-9");
  });

  it("drops the param entirely when cleared", () => {
    search = "run=run-7";
    render(<Probe />);
    screen.getByRole("button", { name: "clear" }).click();
    expect(replace).toHaveBeenCalledWith("/backtests", { scroll: false });
  });
});
