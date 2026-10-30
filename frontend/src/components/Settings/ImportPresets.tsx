import { MappingField, ImportPreview } from './ImportControls'
import { controlClass } from '@/components/Shared/Controls'
import { ImportSection } from './ImportSection';

import { useEffect, useRef, useState } from "react";
import type { Configuration, ImportProfile } from "@/api/configuration";
import { apiRequest } from "@/api/client";
import { Plus, Copy, Trash2 } from "lucide-react";
import { SettingsSelect } from "./Controls";

const input = controlClass
const button = "settings-secondary-button";
const fields = [
  "USERNAME",
  "ROLE_NAME",
  "USER_GROUP",
  "FIRST_NAME",
  "LAST_NAME",
  "EMAIL",
  "USER_VALID_FROM",
  "USER_VALID_TO",
  "ROLE_VALID_FROM",
  "ROLE_VALID_TO",
  "USER_LOCKED",
  "USER_TYPE",
];
const labels: Record<string, string> = {
  USERNAME: "Username (required)",
  ROLE_NAME: "Assigned role",
  USER_GROUP: "SAP User Group",
  FIRST_NAME: "First name",
  LAST_NAME: "Last name",
  EMAIL: "Email",
  USER_VALID_FROM: "User valid from",
  USER_VALID_TO: "User valid to",
  ROLE_VALID_FROM: "Role valid from",
  ROLE_VALID_TO: "Role valid to",
  USER_LOCKED: "Account lock",
  USER_TYPE: "User type",
};

export function PresetActions({
  draft,
  onChange,
  user = false,
}: {
  draft: Configuration;
  onChange: (value: Configuration) => void;
  user?: boolean;
}) {
  const key = user ? "user_import_profiles" : "import_profiles",
    active = user ? "active_user_import" : "active_import";
  const selected = draft[key].find((p) => p.id === draft[active])!;
  const add = (duplicate: boolean) => {
    const id = `import-${crypto.randomUUID()}`.slice(0, 40);
    const preset: ImportProfile = duplicate
      ? {
          ...structuredClone(selected),
          id,
          name: `${selected.name.slice(0, 80)} copy`,
          version: 1,
        }
      : {
          id,
          name: "Custom CSV format",
          version: 1,
          mapping: {},
          delimiter: "auto",
          encoding: "auto",
        };
    onChange({ ...draft, [key]: [...draft[key], preset], [active]: id });
  };
  return (
    <div className="preset-actions">
      <button
        type="button"
        className="settings-secondary-button preset-action"
        aria-label="Create preset"
        title={draft[key].length >= 20 ? "Maximum 20 presets; delete a custom preset first" : "Create preset"}
        disabled={draft[key].length >= 20}
        onClick={() => add(false)}
      >
        <Plus size={16} aria-hidden="true"/><span>Create preset</span>
      </button>
      <button
        type="button"
        className="settings-secondary-button preset-action"
        aria-label="Duplicate preset"
        title={draft[key].length >= 20 ? "Maximum 20 presets; delete a custom preset first" : "Duplicate preset"}
        disabled={draft[key].length >= 20}
        onClick={() => add(true)}
      >
        <Copy size={16} aria-hidden="true"/><span>Duplicate preset</span>
      </button>
      <button
        type="button"
        className="settings-secondary-button preset-action"
        aria-label="Delete preset"
        title={selected.id === "default" ? "Built-in presets cannot be deleted" : "Delete custom preset; source data is retained"}
        disabled={selected.id === "default"}
        onClick={() => {
          if (
            window.confirm(
              `Delete import preset “${selected.name}”? The CSV file and imported data will not be deleted. Apply settings to save this change.`,
            )
          )
            onChange({
              ...draft,
              [key]: draft[key].filter((p) => p.id !== selected.id),
              [active]: "default",
            });
        }}
      >
        <Trash2 size={16} aria-hidden="true"/><span>Delete preset</span>
      </button>
    </div>
  );
}

export function UserSourceEditor({
  draft,
  onChange,
  active = true,
}: {
  draft: Configuration;
  onChange: (value: Configuration) => void;
  active?: boolean;
}) {
  const preset = draft.user_import_profiles.find(
    (p) => p.id === draft.active_user_import,
  )!;
  const [headers, setHeaders] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const signature = JSON.stringify([draft.user_csv_path, preset]);
  const currentSignature = useRef(signature);
  currentSignature.current = signature;
  const [report, setReport] = useState<{
    samples?:Record<string,string>[];
    parsed_rows: number;
    unique_users: number;
    assignments: number;
    duplicate_rows: number;
    warnings: string[];
  } | null>(null);
  const edit = (patch: Partial<ImportProfile>) =>
    onChange({
      ...draft,
      user_import_profiles: draft.user_import_profiles.map((p) =>
        p.id === preset.id ? { ...p, ...patch } : p,
      ),
    });
  useEffect(() => {
    let live = true;
    if (!active) return;
    setHeaders([]);
    setReport(null);
    setError("");
    if (!draft.user_csv_path) {
      setMessage("Choose a local user export. No user data is uploaded.");
      return;
    }
    setMessage("Inspecting user CSV columns…");
    const timer = setTimeout(() => {
      void apiRequest<{ detected_columns: string[]; issues: string[] }>(
        "/api/user-import/headers",
        "POST",
        { data_csv_path: draft.user_csv_path, profile: preset },
      )
        .then(async (result) => {
          if (live) {
            setHeaders(result.detected_columns);
            setMessage(
              result.issues.join(" ") ||
                "Columns detected. Review the preview before applying.",
            );
            const preview = await apiRequest<NonNullable<typeof report>>("/api/user-import/preview", "POST", { data_csv_path: draft.user_csv_path, profile: preset });
            if (live) setReport(preview);
          }
        })
        .catch((e) => {
          if (live) {
            setError(e.message);
            setMessage("");
          }
        });
    }, 400);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [
    active,
    draft.user_csv_path,
    preset.id,
    preset.delimiter,
    preset.encoding,
    JSON.stringify(preset.mapping),
    retry,
  ]);
  const preview = async () => {
    setBusy(true);
    setError("");
    setReport(null);
    const expected = signature;
    try {
      const result = await apiRequest<NonNullable<typeof report>>(
        "/api/user-import/preview",
        "POST",
        { data_csv_path: draft.user_csv_path, profile: preset },
      );
      if (currentSignature.current === expected) setReport(result);
    } catch (e) {
      if (currentSignature.current === expected)
        setError(e instanceof Error ? e.message : "User CSV preview failed.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      aria-label="User access CSV configuration"
      className="import-source-panel space-y-4"
    >
      <ImportSection step={2} title="CSV Import Format" description="Choose a built-in format or create a reusable custom preset.">
      <div className="import-preset-toolbar">
      <label className="block text-sm">
        User CSV Import Format
        <SettingsSelect
          className={input}
          value={draft.active_user_import}
          onChange={(e) =>
            onChange({ ...draft, active_user_import: e.target.value })
          }
        >
          {draft.user_import_profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} · {p.id === "default" ? "Built-in" : "Custom"}
            </option>
          ))}
        </SettingsSelect>
      </label>
      <PresetActions draft={draft} onChange={onChange} user />
      </div>
      <label className="block text-sm">
        User import preset name
        <input
          className={input}
          disabled={preset.id === "default"}
          maxLength={100}
          value={preset.name}
          onChange={(e) => edit({ name: e.target.value })}
        />
      </label>
      <details className="settings-advanced">
        <summary>Advanced user CSV options</summary>
        <div className="grid sm:grid-cols-2 gap-3">
        <label>
          Delimiter
          <SettingsSelect
            className={input}
            value={preset.delimiter}
            onChange={(e) => edit({ delimiter: e.target.value })}
          >
            {[
              ["auto", "Auto detect"],
              [",", "Comma"],
              [";", "Semicolon"],
              ["\t", "Tab"],
              ["|", "Pipe"],
            ].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </SettingsSelect>
        </label>
        <label>
          Encoding
          <SettingsSelect
            className={input}
            value={preset.encoding}
            onChange={(e) => edit({ encoding: e.target.value })}
          >
            {["auto", "utf-8-sig", "utf-16", "cp1252"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </SettingsSelect>
        </label>
        </div>
      </details>
      </ImportSection>
      <ImportSection step={3} title="Column mapping" description="Columns are inspected automatically. Manual mappings are preserved.">
      <p role="status" className="text-sm">
        {message}
      </p>
      {error && (
        <p role="alert" className="text-[var(--error)]">
          {error}
        </p>
      )}
      <button
        type="button"
        className={button}
        disabled={!draft.user_csv_path || busy}
        onClick={() => setRetry((n) => n + 1)}
      >
        Detect user columns
      </button>
      <div className="import-mapping-grid">
        {fields.map((field) => (
          <MappingField key={field} field={field} label={labels[field]} accessibleLabel={`User column ${field}`} value={preset.mapping[field]||''} columns={headers} required={field==='USERNAME'} disabled={busy} onChange={value=>{setReport(null);const mapping={...preset.mapping};if(value)mapping[field]=value;else delete mapping[field];edit({mapping})}}/>

        ))}
      </div>
      </ImportSection>
      <ImportSection step={4} title="Validation & preview" description="Review the parsed data before applying both sources together.">
      <button
        type="button"
        className={button}
        disabled={!draft.user_csv_path || busy}
        onClick={() => void preview()}
      >
        {busy ? "Previewing…" : "Preview user import"}
      </button>
      {report && <ImportPreview fileName={draft.user_csv_path.split(/[\\/]/).pop()} metrics={[{label:'Parsed rows',value:report.parsed_rows},{label:'SAP users',value:report.unique_users},{label:'Assignments',value:report.assignments},{label:'Identical duplicate rows',value:report.duplicate_rows}]} warnings={report.warnings} samples={report.samples||[]}/>}
      </ImportSection>
    </section>
  );
}
