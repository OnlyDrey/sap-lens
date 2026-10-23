import { apiRequest } from "./client";
export interface Assignment {
  id: number;
  username: string;
  role_name: string;
  role_description?: string;
  transaction_roles?: string[];
  user_group: string;
  scope: "business" | "release" | "other";
  valid_from: string | null;
  valid_to: string | null;
  status: string;
  account_status: string;
  user_locked: boolean | null;
  match_status: string;
  catalogue_roles: string[];
  tcodes: string[];
  tcode_count: number;
  release: ReleaseInfo | null;
}
export interface ReleaseInfo {
  parsed: boolean;
  document_type: string | null;
  release_group: string | null;
  release_strategy: string | null;
  opaque_scope?: string;
  opaque_suffix?: string;
}
export interface UserRow {
  username: string;
  user_key: string;
  groups: string[];
  first_name: string;
  last_name: string;
  email: string;
  account_status: string;
  lock_status: string;
  relevant_roles: number;
}
export interface UserDetail extends UserRow {
  data_revision: string;
  mapping_available?: boolean;
  unmapped_assignments?: number;
  items: Assignment[];
  total: number;
  offset: number;
  limit: number;
  retained_assignments: number;
  account_total: number;
  account_offset: number;
  names_total: number;
  emails_total: number;
  names: [string, string][];
  emails: string[];
  accounts: {
    valid_from: string | null;
    valid_to: string | null;
    locked: boolean | null;
    user_type: string;
    user_group: string;
    status: string;
  }[];
  as_of: string;
}
export interface ReleaseRow extends ReleaseInfo {
  role_name: string;
  assigned_users: number;
  assignment_count: number;
  statuses: string[];
  valid_from: string | null;
  valid_to: string | null;
  missing_dates: boolean;
}
export interface Cell {
  user_group: string;
  document_type: string;
  release_group: string;
  release_strategy: string;
  user_count: number;
}
export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  loaded?: boolean;
  catalogue_loaded?: boolean;
  as_of?: string;
  groups?: string[];
}
export interface ReleasePage extends Page<ReleaseRow> {
  matrix: Cell[];
  matrix_total: number;
  matrix_offset: number;
}
export const accessQuery = <T>(
  path: string,
  params: Record<string, string | number | boolean>,
) =>
  apiRequest<T>(
    `/api/access/${path}?${new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])))}`,
  );
