"""Phase 2 offline detection & analysis tooling for the archived Cowrie dataset.

Nothing in this package talks to the (decommissioned) sensor or the AWS
pipeline. It reads the local archive of the 14-day run, rebuilds source-IP
attribution offline, writes ECS-aligned documents to a local Elasticsearch,
and deploys the repo's Sigma rules to the local Kibana detection engine.
"""
