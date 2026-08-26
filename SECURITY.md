# Security policy

## Supported version

Security fixes are provided for the latest published release.

## Reporting a vulnerability

Please report security issues privately to the maintainer before opening a
public issue. Do not attach real project files, server paths, credentials,
customer names or licensed audio.

Include a minimal generated reproducer where possible. Reports involving path
traversal, symlink handling, unsafe filesystem writes, report tampering or
malformed project parsing are especially important.

## Security boundaries

Scanning is read-only: the only file written is the report itself, to a
caller-chosen path, via a temporary file and an atomic replace. Nothing under
the scanned root is opened for writing.

Cleanup moves files into a recoverable quarantine session. Permanent deletion
is reachable only for a completed exact-rewrite or backup-policy session, after
a mandatory 30-day recovery window, macOS owner authentication, an exact typed
confirmation, and a backend revalidation of every recorded path and digest.
Binary project rewriting stays limited to registered exact profiles on roots
explicitly marked as disposable copies.

Reports live in macOS Application Support; sessions live below the selected
root's dedicated hidden control directory. The app performs no
privilege escalation and does not follow directory symlinks.

There is no telemetry or automatic network request. Clicking the support button
explicitly opens the system browser.
