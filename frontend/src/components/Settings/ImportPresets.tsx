import { SourceStatus } from "./SourceStatus";
import { useQuery } from "@tanstack/react-query";
import { fetchConfiguration } from "@/api/configuration";
import { Combobox } from "@/components/Shared/Combobox";
import { useEffect, useRef, useState } from "react";
import type { Configuration, ImportProfile } from "@/api/configuration";
import { apiRequest, applicationToken } from "@/api/client";
import { FolderOpen, Plus, Copy, Trash2 } from "lucide-react";
import { SettingsSelect } from "./Controls";

const input =
  "w-full rounded-lg border px-3 py-2 text-sm bg-[var(--surface2)] border-[var(--border)] text-[var(--text)]";
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
  USER_GROUP: "SAP user group",
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
    <div className="flex flex-wrap gap-2">
      <button
        type="button"
        className={button}
        title={draft[key].length >= 20 ? "Maximum 20 presets; delete a custom preset first" : undefined}
        disabled={draft[key].length >= 20}
        onClick={() => add(false)}
      >
        <Plus size={16} aria-hidden="true"/> Create preset
      </button>
      <button
        type="button"
        className={button}
        title={draft[key].length >= 20 ? "Maximum 20 presets; delete a custom preset first" : undefined}
        disabled={draft[key].length >= 20}
        onClick={() => add(true)}
      >
        <Copy size={16} aria-hidden="true"/> Duplicate preset
      </button>
      <button
        type="button"
        className={button}
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
        <Trash2 size={16} aria-hidden="true"/> Delete preset
      </button>
    </div>
  );
}

export function UserSourceEditor({
  draft,
  onChange,
  native,
  active = true,
}: {
  draft: Configuration;
  onChange: (value: Configuration) => void;
  native: boolean;
  active?: boolean;
}) {
  const { data: configuration } = useQuery({ queryKey: ['configuration'], queryFn: fetchConfiguration });
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
      <h2 className="font-semibold">User Access CSV</h2>
      <p className="text-sm">
        Independent from the role catalogue. USERNAME is required; a blank
        ROLE_NAME retains a directory-only user.
      </p>
      <div className="source-file-row">
      <label className="block text-sm">
        User CSV file location
        <input
          className={input}
          value={draft.user_csv_path}
          maxLength={4096}
          onChange={(e) =>
            onChange({ ...draft, user_csv_path: e.target.value })
          }
        />
      </label>
      <button
        type="button"
        className={button}
        title={!native ? "File browsing is available in the Windows app; enter a full path here." : "Choose a User Access CSV"}
        disabled={!native || busy}
        onClick={() => {
          void window.pywebview?.api
            .choose_csv(applicationToken())
            .then((path) => {
              if (path) onChange({ ...draft, user_csv_path: path });
            })
            .catch(() =>
              setError(
                "The native file picker could not open. Enter an absolute CSV path instead.",
              ),
            );
        }}
      >
        <FolderOpen size={16} aria-hidden="true"/> Browse for user CSV…
      </button>
      </div>
<SourceStatus savedPath={configuration?.settings.user_csv_path || ""} validated={Boolean(report)}/>
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
      </details>
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
      <div className="grid sm:grid-cols-2 gap-3">
        {fields.map((field) => (
          <label key={field} className="text-sm">
            {labels[field]}
            <Combobox label={`User column ${field}`} value={preset.mapping[field] || ''} allowCustom={false}
              clearLabel="Automatic mapping" placeholder="Automatic mapping" options={[...headers, ...Object.values(preset.mapping)]}
              onChange={value => { setReport(null); const mapping = { ...preset.mapping }; if (value) mapping[field] = value; else delete mapping[field]; edit({ mapping }) }}/>
            <small className="text-[var(--muted)]">{field === 'USERNAME' ? 'Required' : 'Optional'} · {preset.mapping[field] ? headers.includes(preset.mapping[field]) ? 'Manual mapping' : 'Mapped column missing' : headers.some(h => h.replace(/[^a-z0-9]/gi, '').toUpperCase() === field.replace(/_/g, '')) ? 'Automatically detected' : 'Not detected'}</small>
          </label>
        ))}
      </div>
      <button
        type="button"
        className={button}
        disabled={!draft.user_csv_path || busy}
        onClick={() => void preview()}
      >
        {busy ? "Previewing…" : "Preview user import"}
      </button>
      {report && (
        <div role="status" className="text-sm space-y-2">
          <p>
            {report.parsed_rows} rows · {report.unique_users} users ·{" "}
            {report.assignments} assignments · {report.duplicate_rows} identical
            duplicate rows
          </p>
          {report.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
          <p>
            Preview only. Save and load CSV applies both sources atomically.
          </p>
        </div>
      )}
    </section>
  );
}
