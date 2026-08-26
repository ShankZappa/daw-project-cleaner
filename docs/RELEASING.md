# Releasing and recall

The application bundle cannot be distributed: it is ad-hoc signed, there is no
Apple Developer account, and no notarization. See
`docs/MASS_USE_READINESS.md` §1. **The Python package is what outside users
receive.** The `.app` is a local build for the studio.

## What ships

| Artifact | Audience | Signing |
|---|---|---|
| `daw_project_cleaner-<version>-py3-none-any.whl` | anyone | none needed |
| `daw_project_cleaner-<version>.tar.gz` | anyone | none needed |
| `DAW Project Cleaner.app` | the author's machines, hand-delivered | ad-hoc, local build only |

The package has **no third-party dependencies** and requires Python 3.9 or
later.

## Before every release

1. `python3 -m unittest discover` — all tests pass.
2. `swiftc -target arm64-apple-macosx11.0 -typecheck native/App.swift`.
3. `sh scripts/check_public_surface.sh` — no private production data in any
   tracked file. This is not optional: the documents once named real client
   projects, server share paths and the studio LAN address.
4. The version is identical in `daw_project_cleaner/__init__.py`,
   `pyproject.toml`, `resources/Info.plist` and `native/App.swift`.
   `daw-project-cleaner --version` prints it, and every report and quarantine
   session records it as `tool_version`.
5. `CHANGELOG.md` has an entry for the version.
6. Build and inspect the package:

   ```sh
   python3 -m build
   python3 -c "import zipfile,sys; print('\n'.join(zipfile.ZipFile(sys.argv[1]).namelist()))" dist/*.whl
   tar tzf dist/*.tar.gz | grep -E 'internal-research|work-reports|releases' && echo LEAK
   ```

7. Install the wheel into a clean virtual environment and run one full
   scan → quarantine → restore cycle against generated fixtures.

## Recall

There is no telemetry, no update check and no way to reach an installed copy.
That is a deliberate privacy property and it makes recall a manual process.

1. Yank the release from the index so no new installation picks it up.
2. Publish a fixed version immediately; a yank alone leaves existing users on
   the defect.
3. Write to every known user directly. This is why the beta stays a **named**
   beta: an anonymous user base cannot be warned.
4. Record the defect, the affected versions and the fix in `CHANGELOG.md` under
   the fixed version, so anyone reading the history can tell whether the copy
   they hold is affected.

Because a report and a session both record `tool_version`, a user can be asked
which version produced a given report, and an affected session can be
identified without guessing.

## Why the beta is named

An open release cannot be recalled, cannot be warned and produces no evidence
that refusal paths behaved correctly on archives nobody has seen. A small set
of named users, each asked to return the session `audit.jsonl` after a run, is
the only way this project gets field evidence without telemetry.
