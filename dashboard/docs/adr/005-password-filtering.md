# ADR-005 — Attempted-password dictionary filtering

**Status:** Accepted
**Date:** 2026-04-28
**Phase introduced:** Phase 1 (decision); Phase 2 (implementation)

## Context

Cowrie captures every password an attacker tries against the honeypot, in plaintext, in `cowrie.login.failed` and `cowrie.login.success` events. The dashboard's most striking single visualization is the "top passwords attackers attempted" bar chart — it makes the educational point of the project visceral.

But the same field that captures `123456` and `password` also captures whatever an attacker happens to type. That can include:

- The attacker's own real credential, accidentally pasted (people do this).
- A victim's reused credential, stolen from one breach and sprayed against random hosts (this is the entire credential-stuffing playbook).
- A randomly typed string that happens to look like a real password.

Publishing those values verbatim on a recruiter-visible public dashboard is an editorial choice with real consequences. The dashboard is portfolio infrastructure — the legitimacy story matters.

A blanket "redact everything" loses the educational signal. A blanket "publish everything" creates a non-zero risk of publishing somebody's real password.

## Decision

The ingest Lambda classifies every attempted password against a bundled known-bad attack-dictionary list:

- **Source:** the top ~5000 entries from public common-password lists (SecLists `Common-Credentials/`, Cowrie operator writeups, breached-password compilations as published in academic security literature). Bundled at `dashboard/functions/shared/data/password_dictionary.txt`. Loaded once at Lambda cold start into a `frozenset`.
- **If the attempted password is in the dictionary**, store it as-is in the `password` attribute. The dashboard surfaces it.
- **If the attempted password is NOT in the dictionary**, store `<filtered:len=N>` in `password` (where N is the original length) and store the actual value in `password_raw`. `password_raw` is **never** returned by any API endpoint, never indexed by any GSI, and never logged in CloudWatch.

The dashboard footer notes: "Passwords shown are dictionary-classified attempts from the bundled attack-dictionary list; non-dictionary attempts are length-redacted."

## Consequences

**Positive:**
- The "top passwords" visualization remains sharp — dictionary attempts are the actual signal in honeypot data anyway. ~95%+ of real attacker traffic uses dictionary passwords.
- A real victim's credential, even if sprayed at the honeypot, never appears on the dashboard.
- An attacker testing their own real password against the honeypot to confirm the trap doesn't have it published.
- Length is preserved for filtered values, so the visualization can still surface signal like "many 24-character entropy-shaped attempts" if relevant.

**Negative:**
- The dictionary is finite. Any attacker password not in the bundled 5K is redacted, including possibly-novel attack patterns. We accept this — the long tail is by definition not a trend, and Phase 11 (real-data tuning) re-sets the dictionary against observed reality.
- We carry `password_raw` in DynamoDB. It costs storage and creates a non-zero exfiltration target. Mitigations: the API never returns it, GSIs never project it, IAM policies for read-side roles deny `dynamodb:GetItem` projections that include `password_raw` (enforced via API DTO mapping; see Phase 4).
- "Plaintext password storage" is uncomfortable to write down even with the safeguards. Documented in this ADR explicitly so the trade-off is discoverable.

## Alternatives considered

1. **Publish all passwords verbatim, no filter.** Originally proposed in PROJECT_PLAN.md v1.0 as ADR-005. Rejected on review — the editorial risk on a recruiter-visible dashboard outweighs the marginal educational benefit over a dictionary-filtered view.
2. **Hash all passwords on ingest, display SHA-256.** Rejected — destroys the visualization. Recruiters don't read SHA-256 sums.
3. **Length-redact everything, no dictionary.** Rejected — the dashboard's most engaging chart becomes a list of "5-char" / "8-char" / "12-char" with no semantic content.
4. **Bloom filter against `Have I Been Pwned`.** Rejected — would require either bundling a multi-GB filter or making a network call per ingest event. Both impractical at our cost target. The bundled top-5K dictionary captures the vast majority of attacker dictionary use anyway.
5. **Manual review queue.** Rejected — the volume (10K events/day) makes this impossible for a single operator running a portfolio project.
