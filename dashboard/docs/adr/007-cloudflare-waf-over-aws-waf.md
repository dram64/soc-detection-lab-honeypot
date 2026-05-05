# ADR-007 — Cloudflare proxied DNS as edge WAF (no AWS WAF)

**Status:** Accepted
**Date:** 2026-04-28
**Phase introduced:** Phase 1 (decision); Phase 8 (implementation)

## Context

The dashboard is a public read-only single-page app fronted by S3 + CloudFront. It needs:

- DDoS mitigation (a single Hacker News spike could push CloudFront egress costs past the $50 account budget cap; PROJECT_PLAN.md §10).
- WAF coverage on the API path (rate limiting, bot management, basic OWASP managed rules).
- TLS termination at the edge.
- A custom domain `dashboard.dram-soc.org` with valid certificate.

`dram-soc.org` is registered through Cloudflare; Cloudflare manages DNS for the domain. Cloudflare's free tier includes:

- Unmetered DDoS protection (L3/4/7).
- A free WAF with managed rules (CF "Free WAF Managed Ruleset").
- Free bot management (basic).
- Free SSL with cert at the edge.
- Rate limiting (limited rules count on free tier; sufficient for our shape).

AWS WAF on CloudFront costs:

- $5.00/month per web ACL.
- $1.00/month per rule.
- $0.60 per 1M requests.

For a 1-ACL + 2-rule deployment at our request volume: ~$5.40/month. PROJECT_PLAN.md §9 estimates this is the single largest line item in the AWS bill — bigger than DynamoDB + Lambda + API GW + CloudFront + CloudWatch combined.

## Decision

**Skip AWS WAF.** Use Cloudflare's proxied DNS (orange cloud) as the public-facing edge:

- `dashboard.dram-soc.org` resolves to Cloudflare anycast IPs.
- Cloudflare's free WAF / DDoS / bot management inspects every request.
- Cloudflare proxies the request to CloudFront over HTTPS.
- CloudFront sees only Cloudflare egress IPs.
- The CloudFront origin is restricted to S3 via Origin Access Control.

The "double-CDN hop" cost is real but small (~10–30 ms of additional TLS termination latency). For a dashboard refreshing every 30 s, this is invisible to the user.

## Consequences

**Positive:**
- Saves ~$5.40/month — drops the project monthly total from ~$8/mo to ~$2.60/mo, comfortably under the $5/mo additive target.
- Cloudflare's DDoS protection is materially better than AWS WAF's rate-based rule for L3/4 attacks, which is the realistic threat for a small portfolio dashboard.
- Cloudflare's "I'm Under Attack" mode is a one-click panic button (see `dashboard/docs/runbooks/viral-traffic.md`).
- TLS termination + cert management is simpler at the Cloudflare edge.

**Negative:**
- CloudFront sees Cloudflare IPs in access logs, not real client IPs. `CF-Connecting-IP` header is preserved; if we ever want IP-level analytics on dashboard *visitors* (we don't, today), we'd add a CloudFront function or Lambda@Edge to extract it.
- Two CDN vendors to operate (Cloudflare for edge, CloudFront for origin shielding + ACM cert host). Acceptable; Cloudflare-side config is approximately a single proxy toggle and one rate-limit rule.
- If Cloudflare has an outage, the dashboard goes dark even if CloudFront is healthy. Acceptable risk for a portfolio piece.
- AWS WAF's managed rule sets are arguably more battle-tested for OWASP-shaped attacks. We accept this — the dashboard has no write surface, so OWASP injection categories are largely inapplicable.

## Alternatives considered

1. **Keep AWS WAF, eat the $5.40/mo.** Rejected on cost (it's the biggest line item in the bill for marginal benefit).
2. **No edge protection at all.** Rejected — a single viral spike could exit the CloudFront free tier and breach the $50 budget cap.
3. **Cloudflare DNS-only (grey cloud) + AWS WAF.** Rejected — pays for AWS WAF without leveraging Cloudflare's free WAF and DDoS, which we have for free already.
4. **API Gateway throttling alone.** Rejected — protects the API path but not the static bundle's CloudFront egress; viral image-loading on the static bundle could still drive cost.
