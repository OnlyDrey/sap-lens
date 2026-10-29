# Desktop workspace and themes (1.2)

## Startup and recovery

A self-contained SAP Lens document is shown before backend readiness, with the product logo and real status messages. Service startup runs off the GUI thread. The app verifies its owned listener and instance identity before navigating to the application. Configuration and role loading then use the actual API state. There are no progress percentages. The default startup uses the SAP Lens dark identity; saved colors are applied as soon as configuration is available.

Startup errors retain a recovery message and guarded Close action. Connection failure offers Retry; a missing/invalid CSV keeps Settings available. A slow read can be canceled from Data Source & Import. Closing during startup cancels readiness waits and cleans up the owned listener. If the application module fails to load, the static document offers an interface retry. Native WebView2 installation failures still use the Windows prerequisite message before a window can be created.

## Full-window settings

Settings occupies the application content area below the compact header. The categorized sidebar stays fixed while content scrolls; the Save/Cancel bar stays visible. Arrow Up/Down and Home/End move between sidebar sections. Forms retain their draft when switching sections. Back and Cancel ask before discarding unsaved changes. Saving validates and persists the complete draft. Metadata and theme edits preserve the dashboard state; material analysis changes reset selections as before.

Module management shows area, type, parent, icon, color and enabled status. Expand an area for label, color and a curated visual icon picker. Search icons by descriptive names; arrow keys move through choices and Enter selects. Reset restores the central registry defaults. SAP area colors remain separate from general theme colors, with contrasting icon foregrounds.

The configured organization name is the primary header heading. An empty or whitespace-only name uses SAP Lens and the product logo. Custom logos retain their proportions inside a maximum 160 × 48 pixel header area with contain sizing. The EXE, taskbar and README remain product-branded.

Successful migration notices use neutral/success styling and can be dismissed for the session. Invalid-configuration recovery stays distinct. Diagnostics shows version, schema/revision, service state, selected source, last successful load and local application directory. Native actions open the fixed log file or configuration folder. Export diagnostics contains only allowlisted versions, platform, status and counts; it excludes paths, organization details, file contents, logs, rules and credentials.

## Theme colors

The default is Dark. Light, Dark and System are persisted; System follows the Windows/WebView media preference and responds to changes while running. Light and Dark have independent palettes, so System can follow appearance without overwriting either.

Six editable colors define each palette:

| Control | Purpose |
| --- | --- |
| Primary color | Header, footer and primary panels |
| Accent color | Primary actions, links and accents |
| Secondary color | Secondary buttons and selected controls (pressed toggles, current list rows) |
| Application background | Workspace canvas |
| Surface / card background | Cards, forms and sidebar |
| Primary text color | Main readable text |

Semantic CSS tokens derive secondary surfaces, hover states, borders, foreground colors and focus rings. Success, warning, error and information colors remain semantic and choose a readable variant. Module classification colors are independent. Buttons choose a contrasting foreground rather than assuming white works on every accent.

Presets: SAP Lens Default, Midnight Blue, Corporate Blue, Neutral Dark and Light. Select a preset to copy it into the draft. Save up to 20 uniquely named custom presets; remove them under Manage custom presets. Names are local user configuration, never repository defaults.

All six colors appear together as a responsive grid of editable controls (five columns when the settings area is at least 62rem wide, three from 44rem, two from 28rem, otherwise one); each uses the visual picker, the six-digit HEX field and Reset for that color's default for the edited mode. Presets show their colors in the same way. Previews are available. The preview represents the header, navigation, role card, buttons and icons without changing the running dashboard. Cancel restores the saved configuration. Applying saves the complete draft, including custom presets.

Primary text must have WCAG AA contrast of at least 4.5:1 against the application background, the card background and the secondary color, in both saved palettes. Palettes saved before Secondary Color existed receive a readable tint of their accent color when they load. Semantic success, warning, error and information colors are never taken from the secondary color. Invalid HEX and low contrast show inline feedback and disable saving; backend validation also rejects them without replacing saved settings. This checks configured primary text pairs, not a complete accessibility certification of every rendered combination. Focus and button foregrounds adapt automatically. Always review the preview for your actual display and module palette.

## Persistence and portability

Colors and custom presets are stored under `theme_colors` in the existing schema-2 settings file, outside the EXE. Earlier schema-2 files receive safe palette defaults in memory while keeping their selected mode; the next explicit save persists them. Existing migration backups, atomic writes and revision checks still apply.

Both redacted and private configuration exports include theme colors and custom preset names. Redacted export still excludes organization branding, SAP rules and CSV paths/records. Treat a custom preset name as shareable only after reviewing it. Import validates colors, contrast, name uniqueness and package limits before applying. Replacing the EXE preserves these settings.

## Validation scope

Linux backend/lifecycle tests mock Windows GUI boundaries. Chromium tests cover settings navigation, retained dashboard selections, unsaved confirmation, theme cancel/save/reload, presets, invalid HEX, contrast, System preference, branding proportions, visual icon selection and responsive layouts at 1280×720, 1366×768 and 1920×1080. Synthetic light/dark screenshots are inspected locally.

These changes subsequently passed automated Windows GUI startup/lifecycle and packaging smoke in [cleanup run 39469463871](https://github.com/OnlyDrey/sap-lens/actions/runs/39469463871). This does not replace the native dialog, visual/high-DPI and clean-PC checklist in DESKTOP.md. Start the manual Build Windows application workflow for future executable builds. Automatic validation intentionally does not build an EXE.

## Settings refinement

See [Settings refinement and validation](../archive/implementation/SETTINGS_REFINEMENT.md) for shared controls,
automatic CSV inspection, the lazy Lucide catalog, save/cancel behavior and platform
validation limits.

Appearance starts with the draft-synchronized live preview, followed by theme/preset controls and compact swatch/hex/reset fields. Logo preview and selection controls use responsive columns. These layout changes do not persist previews or bypass Apply/Cancel.
