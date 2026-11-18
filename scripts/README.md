# Repository scripts

Repository-wide checks and the one helper the active frontend build needs. SAP Lens 2 build, release, installer and deployment scripts are in
[`backend/scripts`](../backend/scripts) ([development](../docs/development/README.md), [deployment](../docs/deployment/README.md)); SAP Lens 1
tooling (including the workflow contract check, icon catalogue sync and license notice) is archived in [`legacy/v1/scripts`](../legacy/v1/scripts/README.md).

| Script | Purpose |
| --- | --- |
| `check-docs.py` | Offline check of relative Markdown links, images and anchors in `README.md`, `AGENTS.md`, `docs/` and `examples/` |
| `check-secrets.py` | Secret and private-value scan of tracked files (`--history` for all refs, `--path DIR` for a release folder, used by `backend/scripts/build-release.*`); prints file, line and rule, never the value |
| `product-version.mjs` | Run by `npm run build` (`prebuild`): keeps `frontend/package.json` equal to the version resource the frontend mirrors, currently SAP Lens 1's `legacy/v1/backend/resources/product-version.json` |
