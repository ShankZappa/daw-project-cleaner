# Product workflow rationale

The application should expose user goals, not development or transport details.
Its final primary workflow is:

1. **Choose folder** — a local disk or mounted server folder;
2. **Scan** — discover projects and establish complete cross-project evidence;
3. **Review and select** — show reclaimable space, Ready projects and exact
   blockers;
4. **Clean to quarantine** — update validated project references and move the
   matching files recoverably;
5. **Recover or delete later** — Restore exact files or permanently delete only
   after the retention and authentication gates pass.

## Why Scan remains

Scan is necessary because a deletion decision cannot safely be made from one
Audio folder or one project in isolation. Before cleanup the backend must know:

- every main project in the chosen scope;
- which media is active, Pool-only, shared or ambiguous;
- whether retained backups protect media;
- whether the exact project writer and Pool topology are supported;
- whether any project or candidate changed after it was read.

These are automatic safety checks inside one Scan action. “Safety Scan”,
“Quick Inventory”, VPN and file-sharing protocol names are implementation or
testing concepts and do not belong in the primary product interface.

## Functions retained in the product

- **Scan & Review**: required evidence and understandable selection;
- **Cleanup**: the user's main storage-reduction goal;
- **Legacy shared archive workflow**: required for folders such as Case A where
  many projects share one Audio tree;
- **Backup policy**: required because archive backups can consume significant
  space and older archives prioritize the final project;
- **Quarantine and Restore**: required rollback protection;
- **Authenticated permanent deletion**: required to actually reclaim storage
  after recovery is no longer needed.

Parser profiles, report schemas, transport performance, controlled validation
phrases and publication mechanics remain internal unless the user must act on
them safely.
