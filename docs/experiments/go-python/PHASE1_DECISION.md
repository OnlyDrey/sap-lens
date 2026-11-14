# Phase 1 decision

## Result: INCOMPLETE. The Windows gate was not passed.

Windows execution was unavailable, so criteria 1, 2 and 4 cannot be assessed and the phase is not a success. Nothing in this repository reports a Windows pass.

## Recommendation: NO-GO for Phase 2. Re-run Phase 1 on Windows first.

This is **not** a verdict against the architecture. It is a gate that has not been tested:

- **What is established (Linux and static analysis):** lifecycle, loopback boundary and secret handling work; the build is reproducible; the bundle for Windows builds reproducibly; about 50 unsigned images from three origins plus the host would have to pass App Control; the benefit over the existing packaging is auditability, not size or speed, and the one-file product has its own unsolved extraction problem under App Control.
- **What decides it, and only Windows can answer:** whether the organization's policy accepts a signer (or any other IT-approved rule) for roughly 50 images in an install folder, and how the existing one-file product behaves under the same policy once signed.
- **Independent of the outcome:** finding F1 (capability handed to any local HTTP client) should be addressed in the product itself, whichever packaging wins ([CAPABILITY_BOOTSTRAP](CAPABILITY_BOOTSTRAP.md)).

## What would turn this into a GO

All of these on a Windows machine with the real policy enforced, evidence in the format of [WINDOWS_VALIDATION](WINDOWS_VALIDATION.md):

1. Harness stages W01 to W13 PASS, or the BLOCKED stages are traced to specific files with enforced Code Integrity events.
2. A concrete, IT-approved path for those files (for example a signer rule for one publisher), stated by the security administrator, not inferred.
3. A measured Windows comparison with the one-dir and one-file builds (startup, memory, size, files, install time, antivirus scan).
4. A decision on class C re-signing versus an upstream-signed interpreter ([SIGNING_CONTRACT](SIGNING_CONTRACT.md)).

## Stop criteria

Stop the experiment if App Control blocks the unsigned third-party images and IT offers no acceptable signing or allow-list path, or if the measured Windows cost in files and scan time outweighs the auditability gain. Then the existing packaging stays, and the host would be considered only as a separate Desktop-shell question.

## Not done, by instruction

No installer, no application functionality migrated, no CI, version, signing or verifier change, no merge into `work` or `main`.
