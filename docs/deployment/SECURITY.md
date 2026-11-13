# Server security boundary

Every server deployment uses local SAP Lens accounts and server-side sessions.
Desktop stays passwordless and requires its exact loopback listener and ephemeral
launch capability. An `X-SAP-Lens` request marker, network address, firewall or
proxy identity header is **not** an application account or permission grant.
Microsoft Entra ID/AD authentication is outside this implementation.

## Application accounts and sessions

The authoritative store is `security/accounts.sqlite3`, separate from the
rebuildable source cache. It contains stable account IDs, Argon2id verifiers,
roles/status, session policy and safe security audit. Migrated legacy PBKDF2
verifiers work unchanged and upgrade after successful sign-in. Passwords require
12–1024 characters with a bounded UTF-8 size; salts are unique. Passwords, reset
codes, cookies and hashes are never audit payloads.

The application uses random HttpOnly, SameSite=Lax session cookies (Secure on
HTTPS), idle/absolute expiry, explicit logout and session-specific CSRF protection
for mutations. Session IDs/CSRF verifiers are hashed in storage. Cookies are never
put in browser localStorage. Failed sign-ins and reset-code attempts are throttled per client:
the fifth failure locks that client for 30 seconds and every further failure doubles
the lock up to 15 minutes; a correct sign-in clears it and 30 quiet minutes start the
count over. There is no permanent account lockout and no per-account lock, so many
source addresses still multiply the possible attempts; password length (12 or more)
and Argon2id are the defence against distributed guessing. Limit records are pruned
above 4,096 clients without evicting an active lock. Denied sign-ins and rejected
activation codes are audited, but only the newest 10,000 of these unauthenticated
denial events are kept; account, role, password, session, policy and migration
events are never removed. Spoofed forwarding
headers do not change the client identity. Session policy defaults to 30-minute
idle and 12-hour absolute expiry and is configurable by administrators.

Settings → **User Management** owns normal create/edit/role/status/reset/revocation
and security audit. Users manage their own profile, password and sessions through
**My Profile**. Disabling/changing an account or resetting/changing its password
invalidates sessions. Last enabled administrator protection is transactional.
Accounts are deactivated rather than deleted; historic identity snapshots remain.

| Role | Permissions |
| --- | --- |
| Administrator | Application administration, imports, settings/branding, accounts, backup/restore, reviews and approvals. |
| Reviewer | Authorized data/reports, reviews/remediation and explicit approvals, including their own. |
| Viewer | Authorized reads/search/comparison/reports; no account, configuration or review mutations. |

Permissions are enforced centrally by the backend. Unknown writes fail closed.
Review and approval remain separate explicit events with justification, evidence,
revision and frozen-period gates. Old reviewer strings and frozen evidence are
not relabelled. Desktop has a stable editable **self-reported local profile**;
it is not equivalent to a server-authenticated account.

## First administrator and local recovery

A genuinely fresh server initializes an empty identity store before other state.
There is no default account/password. Start the server, then locally issue a code:

```text
python backend/server.py --identity-code --data-directory /var/lib/sap-lens
```

Use the installed Python/interpreter and actual protected data directory. Windows
Service Manager has **First-run activation code**. The code is displayed only to
the local operator, expires after 15 minutes, allows five attempts and is consumed
atomically with administrator creation. The web setup page can consume but cannot
issue it. Do not put the code in logs, command arguments or issue attachments.

For an existing administrator, Service Manager **Recover administrator**, or:

```text
python backend/server.py --identity-code --data-directory /var/lib/sap-lens --recover-administrator admin
```

This revokes sessions, blocks the old password and issues one short-lived recovery
code for that existing identity. It never reopens first-run setup. Missing,
unreadable, corrupted or unsupported identity storage is a recoverable startup
failure, not permission to create new empty accounts. Preserve it and use the
verified recovery archive and local operator guidance.

## Transport and proxy configuration

Remote password authentication requires HTTPS. HTTP is permitted only for a real
loopback peer, a loopback listener and a loopback public origin. An old
`SAP_LENS_ALLOW_HTTP=1` acknowledgement does not override this. Docker bridge
traffic is not a loopback peer: the shipped Compose file therefore always serves
direct TLS (a supplied certificate, or a self-signed one generated at installation and
never overwritten) or runs behind a trusted TLS-terminating proxy; see the
[Docker guide](LINUX_DOCKER.md). Never publish plaintext password authentication.

Direct TLS uses `SAP_LENS_TLS_CERT_FILE` and `SAP_LENS_TLS_KEY_FILE`, with an HTTPS
public origin. Files must match, be in date, and cover every allowed alias in typed
SANs. Private keys remain host-local. Windows Service Manager can provision a
self-signed certificate (trust must be established separately) or use existing TLS
files. It cannot silently downgrade HTTPS.

For TLS termination set `SAP_LENS_AUTH=sessions`, an HTTPS public origin, exact
`SAP_LENS_TRUSTED_PROXIES` CIDRs (never `/0`) and a protected
`SAP_LENS_AUTH_SECRET_FILE`. The proxy strips client-supplied forwarding and token
headers, then sets `X-Forwarded-Proto: https` and
`X-SAP-Lens-Proxy-Token` from its private configuration. The backend validates the
real peer plus secret. An identity header does not sign in a user. Restrict backend
network access to the proxy. Do not put the secret in URLs or browser JavaScript.
Trusted X-Forwarded-For is walked from the right for throttling; untrusted peers'
headers are ignored. This is transport validation, not SSO.

POSIX secrets default to owner-only 0600/0400. Dedicated service-group read
0640/0440 requires the corresponding explicit group-read setting and membership;
other access/group write is rejected. Windows reads DACLs and refuses broad groups;
service setup grants only administrators, SYSTEM and the dedicated service SID.
Never fix access by granting Everyone/Users or weakening a private directory.

## Upgrading existing authentication

Stop the owned runtime, preserve original files and configure an external protected
backup key first; see [Backup encryption](BACKUP_RESTORE.md#configure-and-escrow-a-key).
Never point maintenance at a real installation merely to run a test.

Individual-account JSON (`SAP_LENS_AUTH=users`) migrates on stopped startup when a
valid protected key is available. Equivalent explicit local command:

```text
python backend/server.py --migrate-identity --data-directory /var/lib/sap-lens --legacy-auth users --legacy-accounts /etc/sap-lens/users.json
```

The validated old file remains byte-for-byte. Username, enabled state and PBKDF2
verifier are preserved; `read-only` becomes `viewer`. UUIDs are assigned in a staged
version-1 database. A verified encrypted complete application snapshot includes
that exact mapping before atomic activation. Interrupted verified staging resumes
with the same IDs and source digest; corruption/changed source blocks activation.
A crash after activation is reconciled by its migration ID and backup digest.
Legacy account writers now use a recognizable persistent kernel-lock stub: process
exit releases ownership, so a crash does not strand migration. Old unrecognized
presence locks are never deleted or bypassed automatically; inspect the stopped
legacy manager before local recovery. Do not run an old writer against migrated
SQLite or assume editing the preserved JSON changes active accounts.
Failed activation rolls back without modifying old business data or credentials.

Shared Basic/proxy/local access has no verifiable personal account to migrate.
It requires an explicit local administrator identity, never a shared/default
password or unauthenticated setup over populated data:

```text
python backend/server.py --migrate-identity --data-directory /var/lib/sap-lens --legacy-auth basic --new-administrator admin
```

The local command returns a one-time recovery code. Use **Recover administrator**
on the application sign-in page and set a personal password. If interrupted after
activation or the code is lost, issue another local recovery code for that chosen
administrator. Other platforms use the same stopped CLI with their own volume and
key mounts. Service Manager offers **Migrate legacy accounts** for an owned stopped
service; enter the recovery identity for installations without individual accounts.
An unregistered populated directory uses the local CLI before registration.

After migration, account SQLite is authoritative even if the old JSON disappears
or is edited. `users`, `basic`, `proxy` and `local` environment values are legacy
migration inputs, not alternative HTTP authentication paths. Set current
configuration to `sessions`. The retired JSON account command cannot administer
an initialized session store; use User Management.

Migration records and encrypted `pre-identity.slbak` archives are retained under
`.application-backups/identity-migration`. User Management shows them. Confirmation
checks account integrity and **keeps** the archive; deletion requires another explicit
administrator confirmation. Automatic retention never removes them. Preserve the
separate original key for older archives. No old review string is guessed to belong
to a newly assigned account ID.

## Operational boundaries and verification

Use one backend process/storage lease. No automatic schema downgrade, live restore,
remote host restart, OS service change or archive credential rollback is allowed.
Backups contain sensitive SAP/employee/account state; encrypted archives and key
escrow need independent access controls. [Backup/restore](BACKUP_RESTORE.md) defines
contents, exclusions, account acknowledgement and recovery. Do not commit private
settings, datasets, credentials, databases, keys or logs.

Sessions are not SSO or multi-tenant isolation. Concurrent reviewers still obey the
existing revision/evidence gates. Local administrator recovery assumes an operator
already controls protected host storage. Keep OS accounts, key escrow, TLS trust,
network restrictions and retention approvals under organizational control.

Linux synthetic/unit/browser evidence does not certify Windows ACLs, C#/WebView2,
new SCM packages or real systemd. The Docker image and `manage.sh` lifecycle were run
against a real Linux Docker engine (TLS-only sessions, activation, recovery, roles,
revocation, encrypted backup, upgrade, legacy migration, keyed restore, trusted-proxy
admission); that is container integration evidence, not production host acceptance. Historical package acceptance
is bound to that exact package. New native migration/restore acceptance remains
mandatory before declaring this architecture production-ready.
