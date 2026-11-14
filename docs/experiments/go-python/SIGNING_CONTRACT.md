# Signing-aware artifact verification contract (design only)

Nothing here is implemented. No signing change was made and no existing release verification script was modified. It extends, and must not weaken, the current rules: signing is explicit, never falls back to unsigned output, and a payload-bound identity ties every installer to its payload.

## Artifact classes

| Class | Examples | Signing | Identity recorded |
| --- | --- | --- | --- |
| A. Owned PE | `saplens-host.exe`, any SAP Lens launcher | Authenticode with the release publisher, RFC 3161 timestamp | sha256 before and after signing |
| B. Upstream PE, upstream-signed | `vcruntime140*.dll` (Microsoft), a python.org embeddable `python.exe` if adopted | leave untouched; verify the upstream signature and publisher | upstream sha256 (signature included) |
| C. Upstream PE, unsigned | python-build-standalone `python.exe`, `python312.dll`, stdlib `.pyd`/`.dll`; wheel `.pyd` | re-sign as our own, or avoid by choosing class B; the decision is a publisher and policy question | upstream sha256 (from the lock) and distribution sha256 (after signing) |
| D. Non-PE | `.py`, `.pyc`, frontend assets, `manifest.json`, `.pth` | not Authenticode-signable; covered by a signed catalog file or by the signed manifest | distribution sha256 |
| E. Installer | Inno Setup EXE | Authenticode, timestamp | sha256, plus the payload manifest root it carries |

## Two-hash model

Re-signing changes bytes, so the lock's upstream hash cannot be the shipped hash. Every PE record carries both:

```
{ "path": "...", "kind": "pyd", "upstream_sha256": "<lock hash or null for owned files>",
  "distribution_sha256": "<after signing>", "signature": { "state": "signed|unsigned-by-design|upstream-signed",
  "signer_thumbprint": "...", "timestamp": true } }
```

The root hash covers `distribution_sha256` of every file. Verification of the *input* (before signing) uses the lock and `upstream_sha256`; verification of the *output* uses the manifest. The two are linked by one signing step that is the only one allowed to change bytes, and the signed manifest records which files it re-signed, so "same upstream bytes plus our signature" is checkable.

## Order of operations

1. Assemble the unsigned tree from the lock; verify every input hash. (Exists in Phase 0.)
2. Sign class A and C images; leave class B untouched.
3. Compute distribution hashes, write manifest v2, compute the root.
4. Sign `manifest.json` (or a catalog covering class D); the signature covers the root.
5. Build the installer from the signed tree; compute its identity bound to the manifest root; sign the installer.
6. Record installer sha256 and root in the release record. Verification of anything downloaded starts from the installer identity.

Never reorder: hashing before signing produces a manifest that fails its own verification.

## Verifier modes

- **`unsigned`** (today): rejects any certificate table. Unchanged; keeps current behaviour for current releases.
- **`signed`** (new, a separate script): requires an explicit mode flag and an exact publisher allow-list (subject and thumbprint), a valid chain, a trusted timestamp, `distribution_sha256` equal to the manifest, the manifest signature valid, no unlisted image, and `signature.state` consistent with what Windows reports (`Get-AuthenticodeSignature`). A file marked `unsigned-by-design` is allowed only if the policy decision lists it.
- The mode is never inferred from the file content. Requesting signing and receiving unsigned output is an error, never a fallback.

## Runtime checks

- **Install:** full verification in `signed` mode, then ACL the tree administrator-writable only.
- **Start:** the host verifies the manifest signature and the executable image set it is about to load; it refuses to start on mismatch with a distinct exit code and no secret in the message.
- **Native acceptance** stays separate: a signed, verified package that App Control blocks is `BLOCKED`, not `passed`, and not a package defect. A signature is necessary, not sufficient.

## Constraints and open decisions

- Whether to re-sign upstream images (class C) or choose an upstream-signed interpreter (class B): needs the publisher and IT decision, and the python.org embeddable distribution has not been evaluated here.
- Catalog signing for class D is an option, not a decision.
- Windows file-version and product-version identity: keep the existing numeric contract; the host and every owned image reuse it. No version change is proposed.
- Key custody, timestamp authority and certificate lifetime: out of scope; require approved credentials.
