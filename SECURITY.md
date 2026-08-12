# Security policy

## Supply chain

Network installers are never piped directly to a shell. Vendor scripts are
downloaded to temporary files, matched against reviewed digests, and executed
only after verification. Fixed artifacts use tracked SHA-256 or SHA-512 values.
Google Chrome is intentionally updated through the vendor's stable APT channel;
the repository verifies the exact signing-key fingerprint before adding it.

Managed files are written atomically. Unmanaged or user-modified destinations
are preserved and cause a clear failure instead of silent adoption. Credentials,
tokens, browser profiles, caches, traces, and runtime state are never committed.

## AI CLI autonomy

The normal vendor commands retain their native safety behavior. Convenience
launchers `cx`, `cl`, and `gk` explicitly disable approval/permission barriers.
They are intended only for owner-controlled machines with an external security
boundary. The bootstrap never embeds credentials and authentication remains an
interactive post-install handoff.

## Server changes

The composed Ubuntu server install runs from a non-root sudo-capable developer
account. Docker group membership is never granted automatically. Firewall, SSH
hardening, and Fail2ban require explicit flags and retain validation, rollback,
and current-session safeguards. Existing healthy Docker and time providers are
preserved; partial or custom Docker state fails closed.

Report suspected vulnerabilities privately through GitHub Security Advisories.
