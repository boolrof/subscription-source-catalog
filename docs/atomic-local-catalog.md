# Atomic local Catalog snapshots

The existing vgm-local-catalog-snapshot-v1 manifest identifies an immutable Git
tree and its code commit. Only the bounded source index, country handoffs and
country ranking files are published. These files are private local inputs;
public API responses expose only safe metadata and the generation hash.

Install deploy/vps/publish-completed-snapshot as
/usr/local/bin/subscription-source-catalog-publish-completed and install the
local-snapshot.conf service drop-in. It runs only after the Catalog service
succeeds, takes the pipeline lock, requires a clean repository, and publishes
HEAD's immutable tree. Failed or uncommitted cycles retain the previous current.
The hook does not replace the separately managed GeoIP/cleanup pipeline.

The publisher verifies persisted paths, regular files, lengths and SHA-256
before atomic current replacement. Publication is serialized. Retention keeps
eight newest generations plus current, previous and any generation with an
active reader lease. Snapshot readers hold a shared flock on manifest.json;
pruning requires an exclusive nonblocking lock on that same inode. A reader
revalidates inode identity after locking, so a concurrent deletion fails closed.

The publication root is catalog:vgm-catalog mode 2750; files are 0640.
VGM needs read/traverse permissions and SupplementaryGroups=vgm-catalog.
Set VGM_CATALOG_SNAPSHOT_ROOT for the query and action APIs.

Each query pins one generation through materialization, validation and finalist
confirmation. catalog_generation (also in diagnostics) identifies the pinned
snapshot; it does not assert that Catalog supplied a result, since private pool
queries can finish before Catalog discovery. Observability reports the current
snapshot identity independently. Missing or invalid snapshots are errors;
local read failures never silently fall back to network Catalog artifacts.
Country Query HTTP returns generic query_unavailable (503), without paths.

endpoint_country remains a passive discovery hint. Only matching authoritative
live observations and finalist confirmation establish verified_exit_country.

Rollback: restore the saved service drop-ins, previous application commits and
prior current link, then daemon-reload and restart only the two VGM APIs.
Do not restart Catalog or alter routing/SSH/firewall. Remove a newly introduced
Catalog completion hook only while the service is idle. Preserve snapshots used
by running requests; never delete them manually during rollback.
