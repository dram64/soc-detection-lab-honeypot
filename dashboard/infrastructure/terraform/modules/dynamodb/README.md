# Terraform module: dynamodb

Creates the dashboard's single DynamoDB table per ADR-003 (`dashboard/docs/adr/003-single-table-design.md`).

- On-demand billing
- 3 GSIs (gsi1, gsi2, gsi3), each projecting ALL
- DynamoDB Streams: NEW_IMAGE
- PITR: ON
- TTL: `ttl` attribute, epoch seconds
- Server-side encryption with the AWS-owned key
- Deletion protection: ON by default (toggle via `deletion_protection`)

See [PROJECT_PLAN.md §4](../../../../docs/PROJECT_PLAN.md) for the schema and access patterns this module supports.
