import type { ReactNode } from "react";
export const inputClass =
  "rounded-lg border px-3 py-2 text-sm bg-[var(--surface)] border-[var(--border)] text-[var(--text)] min-w-0";
export function Filter({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      {children}
    </label>
  );
}
export function Pagination({
  offset,
  total,
  limit = 50,
  onChange,
  label,
}: {
  offset: number;
  total: number;
  limit?: number;
  onChange: (n: number) => void;
  label: string;
}) {
  return (
    <nav
      aria-label={label}
      className="flex flex-wrap gap-4 items-center py-4 text-sm"
    >
      <button
        className="settings-secondary-button"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`
          : "0 records"}
      </span>
      <button
        className="settings-secondary-button"
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Next
      </button>
    </nav>
  );
}
export const dates = (from: string | null, to: string | null) =>
  `${from || "Unknown"} → ${to || "Unknown"}`;
export function EvidenceNote() {
  return (
    <p className="text-sm text-[var(--muted)]">
      Role-derived transactions are investigation evidence, not proof of
      effective SAP authorization. Missing dates mean unknown validity; account
      status and lock state are separate.
    </p>
  );
}
export function QueryState({
  loading,
  error,
}: {
  loading: boolean;
  error: Error | null;
}) {
  return (
    <>
      {loading && <p role="status">Loading local records…</p>}
      {error && (
        <p role="alert" className="text-[var(--error)]">
          {error.message}
        </p>
      )}
    </>
  );
}
