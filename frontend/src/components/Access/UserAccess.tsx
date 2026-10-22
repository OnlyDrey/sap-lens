import { DetailNavigation, EvidenceBadge } from "@/components/Shared/InvestigationNavigation";
import { Combobox } from "@/components/Shared/Combobox";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  accessQuery,
  type Page,
  type UserRow,
  type UserDetail,
  type Assignment,
} from "@/api/access";
import { RoleIdentifier } from "@/components/Shared/RoleIdentifier";
import {
  dates,
  EvidenceNote,
  Filter,
  inputClass,
  Pagination,
  QueryState,
} from "./Shared";

export function UserAccess({
  initialUser,
  initialRole = "",
  initialTcode = "",
  onRole,
  onRelease,
}: {
  initialUser?: string;
  initialRole?: string;
  initialTcode?: string;
  onRole: (role: string) => void;
  onRelease: (role: string) => void;
}) {
  const listScroll = useRef(0);
  const openUser = (username: string) => { listScroll.current = window.scrollY; setSelected(username) };
  const [search, setSearch] = useState(""),
    [sort, setSort] = useState("username"),
    [descending, setDescending] = useState(false);
  const [group, setGroup] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState(initialUser || "");
  const [role, setRole] = useState(initialRole),
    [tcode, setTcode] = useState(initialTcode),
    [expired, setExpired] = useState(false);
  const [term, setTerm] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setTerm(search), 250);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    setOffset(0);
  }, [term, group, sort, descending, role, tcode, expired]);
  const result = useQuery({
    queryKey: [
      "access-users",
      term,
      group,
      sort,
      descending,
      role,
      tcode,
      offset,
      expired,
    ],
    queryFn: () =>
      accessQuery<Page<UserRow>>("users", {
        search: term,
        group,
        sort,
        descending,
        role,
        tcode,
        offset,
        show_expired: expired,
      }),
  });
  if (selected)
    return (
      <UserDetails
        username={selected}
        onBack={() => { const previous = selected; setSelected(""); requestAnimationFrame(() => {
          const button = [...document.querySelectorAll<HTMLButtonElement>('[data-user]')].find(button => button.dataset.user === previous);
          button?.focus({ preventScroll: true }); window.scrollTo(0, listScroll.current)
        }) }}
        onRole={onRole}
        onRelease={onRelease}
        index={result.data?.items.findIndex(user => user.username === selected) ?? -1}
        total={result.data?.items.length || 0}
        onSelect={setSelected}
        usernames={result.data?.items.map(user => user.username) || []}
      />
    );
  return (
    <section aria-label="User Access" className="space-y-4">
      <h1 className="text-xl font-semibold">User Access</h1>
      <EvidenceNote />
      <div className="investigation-filters"><fieldset><legend>User directory</legend><div className="filter-grid">
        <Filter label="Search users">
          <input
            className={inputClass}
            value={search}
            maxLength={256}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Username, name, email or group"
          />
        </Filter>
        <Filter label="SAP User Group">
          <Combobox label="SAP User Group" value={group} options={result.data?.groups || []} onChange={setGroup} placeholder="All groups; type a group to filter"/>
        </Filter>
        <Filter label="Sort users">
          <select
            className={inputClass}
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            {[
              ["username", "Username"],
              ["group", "User group"],
              ["first_name", "First name"],
              ["last_name", "Last name"],
              ["email", "Email"],
              ["account_status", "Account status"],
              ["relevant_roles", "Relevant role count"],
            ].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Filter>
        <label className="flex gap-2 items-center">
          <input
            type="checkbox"
            checked={descending}
            onChange={(e) => setDescending(e.target.checked)}
          />
          Descending
        </label>
        <label className="flex gap-2 items-center">
          <input
            type="checkbox"
            checked={expired}
            onChange={(e) => setExpired(e.target.checked)}
          />
          Show expired assignments
        </label>
      </div></fieldset></div>
      {(role || tcode) && (
        <div role="status" className="flex gap-3 text-sm">
          <span>
            Evidence filter: {role ? `Role ${role}` : `Transaction ${tcode}`}
          </span>
          <button
            className="underline"
            onClick={() => {
              setRole("");
              setTcode("");
            }}
          >
            Clear evidence filter
          </button>
        </div>
      )}
      <QueryState loading={result.isLoading} error={result.error} />
      {result.data && !result.data.loaded && (
        <p>
          No User Access CSV loaded. Choose the second source in Settings → Data
          Source &amp; Import.
        </p>
      )}
      {result.data?.loaded && !result.data.catalogue_loaded && (
        <p role="status">
          No role catalogue loaded. Assignments are retained as Unmapped;
          transaction access is not inferred.
        </p>
      )}
      {result.data && (
        <>
          <div className="access-table">
            <table>
              <thead>
                <tr>
                  {[
                    "User group",
                    "Username",
                    "First name",
                    "Last name",
                    "Email",
                    "User status / lock",
                    "Relevant roles",
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((user) => (
                  <tr key={user.user_key}>
                    <td>
                      {user.groups
                        .map((group) => group || "Unknown group")
                        .join(", ") || "Unknown"}
                    </td>
                    <td>
                      <button
                        className="underline"
                        data-user={user.username}
                        onClick={() => openUser(user.username)}
                      >
                        {user.username}
                      </button>
                    </td>
                    <td>{user.first_name || "—"}</td>
                    <td>{user.last_name || "—"}</td>
                    <td>{user.email || "—"}</td>
                    <td>
                      {user.account_status} · {user.lock_status}
                    </td>
                    <td>{user.relevant_roles}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.data.total === 0 && result.data.loaded && (
            <p>No users match these filters.</p>
          )}
          <Pagination
            offset={offset}
            total={result.data.total}
            onChange={setOffset}
            label="User pages"
          />
        </>
      )}
    </section>
  );
}

function UserDetails({
  username,
  onBack,
  onRole,
  onRelease,
  index, total, onSelect, usernames,
}: {
  index: number; total: number; onSelect: (name: string) => void; usernames: string[];
  username: string;
  onBack: () => void;
  onRole: (role: string) => void;
  onRelease: (role: string) => void;
}) {
  const [scope, setScope] = useState("business"),
    [status, setStatus] = useState(""),
    [offset, setOffset] = useState(0),
    [accountOffset, setAccountOffset] = useState(0),
    [nameOffset, setNameOffset] = useState(0),
    [emailOffset, setEmailOffset] = useState(0);
  useEffect(() => { setOffset(0) }, [scope, status, username]);
  useEffect(() => { setAccountOffset(0); setNameOffset(0); setEmailOffset(0) }, [username]);
  const result = useQuery({
    queryKey: [
      "access-user",
      username,
      scope,
      status,
      offset,
      accountOffset,
      nameOffset,
      emailOffset,
    ],
    queryFn: () =>
      accessQuery<UserDetail>(`users/${encodeURIComponent(username)}`, {
        scope,
        status: status === "all" ? "" : status,
        show_expired: status === "all",
        offset,
        account_offset: accountOffset,
        name_offset: nameOffset,
        email_offset: emailOffset,
      }),
  });
  const user = result.data;
  return (
    <section aria-label="User details" className="space-y-4">
      <DetailNavigation parent="User Access" current={username} onBack={onBack} index={index} total={total}
        onPrevious={index > 0 ? () => onSelect(usernames[index - 1]) : undefined}
        onNext={index >= 0 && index < total - 1 ? () => onSelect(usernames[index + 1]) : undefined}/>
      <h1 className="text-xl font-semibold">User details</h1>
      <RoleIdentifier value={username} label="username" />
      <QueryState loading={result.isLoading} error={result.error} />
      {user && (
        <>
          <dl className="account-summary">
            <dt>User group</dt>
            <dd>
              {user.groups
                .map((group) => group || "Unknown group")
                .join(", ") || "Unknown"}
            </dd>
            <dt>Full name</dt>
            <dd>
              {user.names
                .map((n) => n.join(" ").trim())
                .filter(Boolean)
                .join(" / ") || "Unknown"}
            </dd>
            <dt>Email</dt>
            <dd>{user.emails.join(", ") || "Unknown"}</dd>
            {user.accounts.length === 1 && <><dt>User validity</dt><dd>{dates(user.accounts[0].valid_from, user.accounts[0].valid_to)}</dd></>}
            <dt>Account status</dt><dd><EvidenceBadge value={user.account_status}/></dd>
            <dt>Account lock status</dt>
            <dd>{user.lock_status}</dd>
          </dl>
          <details className="settings-advanced" open={user.accounts.length !== 1}><summary>User validity and account evidence</summary>
          <div className="access-table">
            <table>
              <thead>
                <tr>
                  <th>User group</th>
                  <th>User validity</th>
                  <th>Account status</th>
                  <th>Locked</th>
                  <th>User type</th>
                </tr>
              </thead>
              <tbody>
                {user.accounts.map((a, i) => (
                  <tr key={i}>
                    <td>{a.user_group || "Unknown"}</td>
                    <td>{dates(a.valid_from, a.valid_to)}</td>
                    <td>{a.status}</td>
                    <td>
                      {a.locked === null ? "Unknown" : a.locked ? "Yes" : "No"}
                    </td>
                    <td>{a.user_type || "Unknown"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            offset={accountOffset}
            total={user.account_total}
            onChange={setAccountOffset}
            label="Account evidence pages"
          />
          </details>
          {user.names_total > 100 && (
            <Pagination
              offset={nameOffset}
              total={user.names_total}
              limit={100}
              onChange={setNameOffset}
              label="Name variant pages"
            />
          )}
          {user.emails_total > 100 && (
            <Pagination
              offset={emailOffset}
              total={user.emails_total}
              limit={100}
              onChange={setEmailOffset}
              label="Email variant pages"
            />
          )}
          <EvidenceNote />
          <p className="text-xs">
            Validity evaluated on {user.as_of}. {user.retained_assignments}{" "}
            assignment records retained.
          </p>
          <nav aria-label="User role sections" className="flex flex-wrap gap-2">
            {[
              ["business", "Business Roles — ZC:*"],
              ["release", "Release Roles — ZO:*"],
              ["other", "Other source assignments"],
            ].map(([v, l]) => (
              <button
                key={v}
                className="settings-secondary-button"
                aria-pressed={scope === v}
                onClick={() => setScope(v)}
              >
                {l}
              </button>
            ))}
          </nav>
          <div className="flex flex-wrap gap-3">
            <Filter label="Assignment status">
              <select aria-label="Assignment status"
                className={inputClass}
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                {[
                  ["", "All non-expired"],
                  ["active", "Currently valid"],
                  ["all", "All assignments"],
                  ["future", "Future"],
                  ["unknown", "Unknown validity"],
                  ["expired", "Expired"],
                ].map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Filter>
          </div>
          <div className="access-table">
            <table>
              <thead>
                <tr>
                  <th>Exact assigned role</th>
                  <th>
                    {scope === "release"
                      ? "PR/PO · Group · Strategy"
                      : "Catalogue match"}
                  </th>
                  <th>Role validity</th>
                  <th>Assignment status</th>
                  <th>
                    {scope === "release"
                      ? "Release investigation"
                      : "Catalogue / transactions"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {user.items.map((a) => (
                  <AssignmentRow
                    key={a.id}
                    assignment={a}
                    onRole={onRole}
                    onRelease={onRelease}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {!user.items.length && (
            <p>
              No assignments in this section for the selected validity filters.
            </p>
          )}
          <Pagination
            offset={offset}
            total={user.total}
            onChange={setOffset}
            label="User assignment pages"
          />
        </>
      )}
    </section>
  );
}

function AssignmentRow({
  assignment: a,
  onRole,
  onRelease,
}: {
  assignment: Assignment;
  onRole: (role: string) => void;
  onRelease: (role: string) => void;
}) {
  return (
    <tr>
      <td>
        <RoleIdentifier value={a.role_name} />
      </td>
      <td>
        {a.scope === "release" ? (
          a.release?.parsed ? (
            `${a.release.document_type} · ${a.release.release_group} · ${a.release.release_strategy}`
          ) : (
            "Unparsed"
          )
        ) : (
          <>
            <EvidenceBadge value={a.match_status}/>
            {a.catalogue_roles.map((name) => (
              <div key={name} className="mt-2"><RoleIdentifier value={name}/></div>
            ))}
          </>
        )}
      </td>
      <td>{dates(a.valid_from, a.valid_to)}</td>
      <td>
        <EvidenceBadge value={a.status}/>
        <br />
        <small>Group: {a.user_group || "Unknown"}</small>
      </td>
      <td>
        {a.scope === "release" ? (
          <button className="underline" onClick={() => onRelease(a.role_name)}>
            Release role details
          </button>
        ) : a.match_status === "exact" || a.match_status === "wildcard" ? (
          <>
            {a.catalogue_roles.map((name) => (
              <button
                key={name}
                className="underline block"
                onClick={() => onRole(name)}
              >
                Role details: {name}
              </button>
            ))}
            <details>
              <summary>{a.tcode_count} associated transactions</summary>
              {a.tcodes.join(", ") || "None in catalogue"}
              {a.tcode_count > a.tcodes.length && (
                <p>
                  Showing the first 100. Open Role details to review all
                  catalogue transactions.
                </p>
              )}
            </details>
          </>
        ) : (
          <span>No transaction access inferred</span>
        )}
      </td>
    </tr>
  );
}
