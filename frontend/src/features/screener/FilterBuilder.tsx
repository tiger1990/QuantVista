"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  CATEGORICAL_FIELDS,
  type FilterClause,
  NUMERIC_FIELDS,
  NUMERIC_OPS,
  validateClause,
} from "@/lib/screener";

const NUMERIC_KEYS = Object.keys(NUMERIC_FIELDS) as (keyof typeof NUMERIC_FIELDS)[];
const CATEGORICAL_KEYS = Object.keys(CATEGORICAL_FIELDS) as (keyof typeof CATEGORICAL_FIELDS)[];
const OP_KEYS = Object.keys(NUMERIC_OPS) as (keyof typeof NUMERIC_OPS)[];

const selectClass =
  "h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none";

interface DraftClause {
  field: string;
  op: string;
  value: string;
}

const isCategorical = (field: string) => field in CATEGORICAL_FIELDS;

function emptyDraft(): DraftClause {
  return { field: "composite_score", op: "gte", value: "" };
}

interface FilterBuilderProps {
  initialFilters: FilterClause[];
  onRun: (filters: FilterClause[]) => void;
}

/**
 * Filter-builder: rows of {field, op, value} constrained to the allow-list. "Run screen" validates
 * each draft clause (dropping invalid) and commits — the parent lifts the applied filters into the
 * URL for shareability. Categorical fields collapse to `eq`.
 */
export function FilterBuilder({ initialFilters, onRun }: FilterBuilderProps) {
  const [rows, setRows] = useState<DraftClause[]>(() =>
    initialFilters.length
      ? initialFilters.map((f) => ({ field: f.field, op: f.op, value: String(f.value) }))
      : [emptyDraft()],
  );

  const update = (i: number, patch: Partial<DraftClause>) => {
    setRows((prev) =>
      prev.map((r, idx) => {
        if (idx !== i) return r;
        const next = { ...r, ...patch };
        // Switching to a categorical field forces the only supported operator.
        if (patch.field !== undefined) next.op = isCategorical(patch.field) ? "eq" : "gte";
        return next;
      }),
    );
  };

  const addRow = () => setRows((prev) => [...prev, emptyDraft()]);
  const removeRow = (i: number) =>
    setRows((prev) => (prev.length === 1 ? [emptyDraft()] : prev.filter((_, idx) => idx !== i)));

  const run = () => {
    const valid = rows
      .map((r) => validateClause(r.field, r.op, r.value))
      .filter((c): c is FilterClause => c !== null);
    onRun(valid);
  };

  return (
    <div className="space-y-3 rounded-lg border border-border p-4">
      <div className="space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Field"
              value={row.field}
              onChange={(e) => update(i, { field: e.target.value })}
              className={selectClass}
            >
              <optgroup label="Scores & fundamentals">
                {NUMERIC_KEYS.map((k) => (
                  <option key={k} value={k}>
                    {NUMERIC_FIELDS[k]}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Categories">
                {CATEGORICAL_KEYS.map((k) => (
                  <option key={k} value={k}>
                    {CATEGORICAL_FIELDS[k]}
                  </option>
                ))}
              </optgroup>
            </select>

            <select
              aria-label="Operator"
              value={row.op}
              onChange={(e) => update(i, { op: e.target.value })}
              disabled={isCategorical(row.field)}
              className={`${selectClass} disabled:opacity-60`}
            >
              {isCategorical(row.field) ? (
                <option value="eq">is</option>
              ) : (
                OP_KEYS.map((op) => (
                  <option key={op} value={op}>
                    {NUMERIC_OPS[op]}
                  </option>
                ))
              )}
            </select>

            <Input
              aria-label="Value"
              value={row.value}
              inputMode={isCategorical(row.field) ? "text" : "decimal"}
              placeholder={isCategorical(row.field) ? "e.g. Financials" : "e.g. 70"}
              onChange={(e) => update(i, { value: e.target.value })}
              className="h-9 w-40"
            />

            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Remove filter"
              onClick={() => removeRow(i)}
            >
              <X className="size-4" />
            </Button>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={addRow}>
          <Plus className="size-4" /> Add filter
        </Button>
        <Button type="button" size="sm" onClick={run}>
          Run screen
        </Button>
      </div>
    </div>
  );
}
