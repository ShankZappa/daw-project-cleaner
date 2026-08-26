"""DAW Project Cleaner: local, safety-first archive scanner and quarantine tool."""

__version__ = "0.11.0"

# Permanent deletion is the only irreversible operation in this tool. A beta
# build sets this to False so the capability is absent rather than merely
# gated: quarantine and Restore deliver most of the value while the tool is
# meeting archives nobody has seen. scripts/build_package.sh --beta writes it.
PURGE_ENABLED = True
