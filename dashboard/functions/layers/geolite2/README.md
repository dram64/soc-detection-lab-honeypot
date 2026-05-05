# GeoLite2 Lambda layer

Holds the MaxMind GeoLite2 Country + ASN .mmdb files used by the ingest Lambda
for src_ip enrichment (PROJECT_PLAN.md §3, ADR-001).

## Files (NOT committed)

The .mmdb files live alongside this README at deploy time but are not stored
in git:

- `GeoLite2-Country.mmdb`
- `GeoLite2-ASN.mmdb`

`.gitignore` excludes `*.mmdb` under this directory.

## Refresh

```bash
MAXMIND_LICENSE_KEY=xxxxxxxxxxxx ./download_geolite2.sh
```

Run this before each deploy that needs a fresh database. Get a free MaxMind
license key at https://www.maxmind.com/en/accounts/<your-id>/license-key.

Phase 9 wires a scheduled Lambda that does this refresh weekly and publishes
a new layer version automatically.

## License

GeoLite2 is licensed CC BY-SA 4.0; attribution is shown in the dashboard
footer (ADR-006 documents the exact wording when Phase 7 lands).
