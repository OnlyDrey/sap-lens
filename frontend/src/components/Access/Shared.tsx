import { Button } from '@/components/Shared/Button'
import { FormField, controlClass } from '@/components/Shared/Controls'
import { LoadingState } from '@/components/Shared/Presentation'
import { Select } from '@/components/Shared/Select'
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
export const PAGE_SIZES = [10, 20, 50, 100] as const
/**
 * Shared pager. Without `pageSizes` it is the plain Previous/Next control. With `pageSizes` it also offers a rows-per-page
 * selector (10, 20, 50 or 100); callers reset or clamp the offset when the size or the filters change.
 */
export function Pagination({
  offset,
  total,
  limit = 50,
  onChange,
  label,
  pageSizes,
  onPageSize,
  unit,
  alwaysShow = false,
}: {
  offset: number;
  total: number;
  limit?: number;
  onChange: (n: number) => void;
  label: string;
  pageSizes?: readonly number[];
  onPageSize?: (size: number) => void;
  /** Names what is counted in the range, for example `users`: "1–50 of 244 users". */
  unit?: string;
  /** Keep the pager (range and disabled buttons) visible when everything fits on one page. */
  alwaysShow?: boolean;
}) {
  const sizable = !!pageSizes && !!onPageSize
  if (!alwaysShow && total <= (sizable ? Math.min(...pageSizes!) : limit)) return null;
  return (
    <nav
      aria-label={label}
      className="assignment-pagination ui-pagination"
      data-sizable={sizable || undefined}
    >
      {sizable && (
        <label className="ui-pagination-size">
          <span>Rows per page</span>
          <Select aria-label={`${label}: rows per page`} value={String(limit)} onChange={(event) => onPageSize!(Number(event.target.value))}>
            {pageSizes!.map((size) => <option key={size} value={size}>{size}</option>)}
          </Select>
        </label>
      )}
      <Button
        size="compact"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        <ArrowLeft size={16} aria-hidden="true"/> Previous
      </Button>
      <span className="ui-pagination-range" role="status">
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}${unit ? ` ${unit}` : ''}`
          : unit ? `0 ${unit}` : "0 records"}
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
