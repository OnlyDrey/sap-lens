import { useEffect, useRef, useState } from "react";
import type { Configuration, ImportProfile } from "@/api/configuration";
import { apiRequest, applicationToken } from "@/api/client";
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
        disabled={draft[key].length >= 20}
        onClick={() => add(false)}
      >
        Create preset
      </button>
      <button
        type="button"
        className={button}
        disabled={draft[key].length >= 20}
        onClick={() => add(true)}
      >
        Duplicate preset
      </button>
      <button
        type="button"
        className={button}
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
        Delete preset
      </button>
    </div>
  );
}

export function UserSourceEditor({
  draft,
  onChange,
  native,
}: {
  draft: Configuration;
  onChange: (value: Configuration) => void;
  native: boolean;
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
        .then((result) => {
          if (live) {
            setHeaders(result.detected_columns);
            setMessage(
              result.issues.join(" ") ||
                "Columns detected. Preview before applying.",
            );
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
      className="settings-card space-y-4"
    >
      <h2 className="font-semibold">User Access CSV</h2>
      <p className="text-sm">
        Independent from the role catalogue. USERNAME is required; a blank
        ROLE_NAME retains a directory-only user.
      </p>
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
        Browse for user CSV…
      </button>
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
              {p.name}
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
            <SettingsSelect
              className={input}
              value={preset.mapping[field] || ""}
              aria-label={`User column ${field}`}
              onChange={(e) => {
                setReport(null);
                const mapping = { ...preset.mapping };
                if (e.target.value) mapping[field] = e.target.value;
                else delete mapping[field];
                edit({ mapping });
              }}
            >
              <option value="">
                Automatic
                {headers.find(
                  (h) =>
                    h.replace(/[^a-z0-9]/gi, "").toUpperCase() ===
                    field.replace(/_/g, ""),
                )
                  ? " — detected"
                  : " — not detected"}
              </option>
              {[...new Set([...headers, ...Object.values(preset.mapping)])].map(
                (h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ),
              )}
            </SettingsSelect>
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
