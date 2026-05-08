#!/usr/bin/env python3
"""Generate Wazuh-compatible passwords for the .env file.

Constraints derived from Phase 1A retry forensics (see PHASE_1A_LOG.md):
- Must contain at least one special char (Wazuh error 5007 policy)
- Must NOT contain $ (docker compose .env variable interpolation)
- Must NOT contain \\ (Wazuh create_user.py JSON encoding breaks on invalid escapes)
- Must NOT contain ` " ' (shell quoting hazards)
- Must NOT contain = < > (env-format / shell-redirection hazards)
- Length: exactly 32 chars

Usage:
    python3 generate-passwords.py [count]

    With no args, prints 1 password.
    With an integer arg, prints that many passwords (one per line).

Designed to be wrapped by a shell script that captures the output into .env.
See README.md "Password generation" section for the canonical .env-write procedure.
"""

import secrets
import string
import sys

# Explicit alphabet: 62 alphanumeric + 9 safe specials.
# Excluded: $ \ ` " ' = < > ? + . , / : ; { } [ ] ( ) | ~
SAFE_SPECIALS = "!@#%^&*_-"
ALPHABET = string.ascii_letters + string.digits + SAFE_SPECIALS


def generate(length: int = 32) -> str:
    """Return a length-char password meeting Wazuh's policy + our constraints."""
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if any(c in SAFE_SPECIALS for c in pw):
            return pw


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for _ in range(count):
        print(generate())
