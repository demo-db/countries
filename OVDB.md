---
ovdb: 1
publish:
  - ./ovdb.yaml
  - ./ovdb-database.json
---

# Countries OVDB publication

The descriptors above configure the publication of the immutable, read-only
Countries reference database through OpenVaultDB. The endpoint remains
unverified until the consumer deployment is complete. Generated schema and
recordset metadata come from the pinned SQLite source rather than a separately
maintained schema.
