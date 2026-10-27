import { Button } from '@/components/Shared/Button'
import { FormField, controlClass } from '@/components/Shared/Controls'
import { LoadingState } from '@/components/Shared/Presentation'
import { formatDate } from '@/lib/dateFormat';
import { ArrowLeft, ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
export const inputClass = controlClass;
export function Filter({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return <FormField label={label}>{children}</FormField>;
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
  if (total <= limit) return null;
  return (
    <nav
      aria-label={label}
      className="assignment-pagination flex flex-wrap gap-4 items-center py-4 text-sm"
    >
      <Button
        size="compact"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        <ArrowLeft size={16} aria-hidden="true"/> Previous
      </Button>
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`
          : "0 records"}
      </span>
      <Button
        size="compact"
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Next <ArrowRight size={16} aria-hidden="true"/>
      </Button>
    </nav>
  );
}
export const dates = (from: string | null, to: string | null) =>
  `${formatDate(from)} → ${formatDate(to)}`;
export function EvidenceNote() {
  return (
    <p className="text-sm text-[var(--muted)]">
      Role-derived transactions are investigation evidence, not proof of
      effective SAP authorization. Missing dates never establish active access; account
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
      {loading && <LoadingState/>}
      {error && (
        <p role="alert" className="text-[var(--error)]">
          {error.message}
        </p>
      )}
    </>
  );
}
