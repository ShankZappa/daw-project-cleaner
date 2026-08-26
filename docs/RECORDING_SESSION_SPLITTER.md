# Recording-session splitter

This future feature addresses one long recording project that contains multiple
songs or takes on a shared timeline. It is separate from splitting several
already independent project files out of one mother folder.

## Evidence sources

The splitter may propose song boundaries only when one or more strong signals
exist:

- named marker or arranger events;
- named folder tracks that map to timeline regions;
- media events clustered into clearly separated time ranges;
- repeated track layout with long global silence between regions;
- explicit user-created cycle ranges;
- overlap with already separated child projects through verified media IDs or
  hashes.

Track names or silence alone are suggestions, not authorization. The UI must
show a timeline preview, proposed ranges, included tracks/media and conflicts.
The user confirms or edits every song boundary before any new project is made.

## Output

For each confirmed range, the application creates a staged latest-version
Nuendo 15 project with the studio's default folder structure, copies or moves all required
media, preserves handles/tails selected by the user and validates the project in
the corresponding DAW. The source recording project remains in central rollback
quarantine for 30 days.

## the Case A master finding

`Case A master.cpr` is Cubase 7.0.6 and contains 13 generically named Audio
tracks plus a marker-track structure. The current reader found no supported
audio filename records and no song-title strings. There is therefore no safe
automatic mapping from its timeline to the 19 separated song projects. It is
excluded from automatic splitting unless a future event/marker parser reveals
explicit boundaries that can be previewed and manually confirmed.
