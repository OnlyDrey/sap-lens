# Architecture

- [System](SYSTEM.md): shared backend/frontend, data flow and runtime entry points.
- [Storage and revisions](STORAGE_AND_REVISIONS.md): snapshots, the SQLite store, fingerprints, staged activation, the data revision token and review integrity.
- [API](API.md): routes, contracts, pagination and source evidence.
- [Security](SECURITY.md): desktop/server boundaries and sensitive-data handling.
- [Privacy](PRIVACY.md): accepted historical P-01 issue and scoped repository review.
- [Desktop integration](DESKTOP.md): WebView2 lifecycle, native operations and acceptance checklist.
- [Design System](DESIGN_SYSTEM.md): semantic tokens, states and themes.
- [SoD](SOD.md): evidence, decisions, periods and reports, identities and migration.
- [Components](COMPONENTS.md): canonical implementations, APIs and safe showcase previews.
- [Navigation](NAVIGATION.md): routes, secondary navigation, content tabs and actions.
- [Appearance](APPEARANCE.md): persisted palettes, branding and settings interaction.

Operational hosting/security configuration belongs to [Deployment](../deployment/README.md);
CSV behavior belongs to [Data](../data/README.md), not a separate platform implementation.
