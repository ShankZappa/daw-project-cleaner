# Design source

The v1 UX gate named in `PROJECT_CONTEXT.md` is being worked through a Claude
Design project:

    https://claude.ai/design/p/b4cc89cb-85e8-46f5-a973-9275c8c47792

The project holds one file per screen. `DAW Project Cleaner.dc.html` is the
application shell; it `dc-import`s the other files as its workspace bodies.

| Design file | Status |
|---|---|
| `DAW Project Cleaner.dc.html` | **implemented** in `native/App.swift` |
| `ScanReview.dc.html` | not implemented — the existing Scan & Review page is used as-is |
| `Cleanup.dc.html` | not implemented — existing page used as-is |
| `Recovery.dc.html` | not implemented — existing page used as-is |
| `AboutPanel.dc.html` | not implemented — the shipped About sheet is used |
| `ProjectDetail.dc.html`, `ScanResults.dc.html` | not implemented |

`support.js` in the design project is the generated `dc-runtime` that renders
the `.dc.html` format in a browser. It is a build artifact of the design tool,
not part of this app, so it is not vendored here.

The `.dc.html` sources are deliberately not copied into this repository either:
the design project is the live source and a vendored copy would go stale
silently. Read them with the design tooling against the project id above.

## How the shell design maps onto AppKit

- **Palette.** The design defines explicit light/dark hex and `oklch` tokens.
  These are implemented as `ShellPalette`, which maps each role onto the macOS
  semantic colour with the same meaning (`text` → `labelColor`, `accent` →
  `controlAccentColor`, and so on). One code path therefore renders both
  palettes and additionally follows the user's accent colour and the
  Increase Contrast setting, which hardcoded hexes cannot do.
- **Title bar.** The design draws its own traffic lights and centred title.
  macOS provides both, so the window keeps the standard title bar and the two
  chrome buttons are added as a trailing `NSTitlebarAccessoryViewController`.
- **Icons.** Emoji in the design (🔍 🧹 ↺ ☀ ☾ ⓘ) become the equivalent SF
  Symbols, which is the native form and inherits weight and tint.
- **Theme switch.** The design starts in `light`. Starting there would force a
  light window onto a Mac in dark mode, so the app follows the system
  appearance until the switch is used once; after that the choice is stored in
  `ShellAppearance`. The control itself stays the two-state switch as designed.
- **About.** The design shows a fixed full-window overlay. macOS sheets are
  the equivalent, and one is already implemented and shipped, so the ⓘ button
  opens that sheet instead of a custom overlay.
- **Nav badge.** `navItems[].badge` is modelled in the design but never set.
  `SidebarNavButton.badge` implements it and is left unset.
