# ADR 0007: whole-device integrity receipt

Status: accepted

Ubuntu fixed runtime hosts and source tools are installed into managed,
versioned trees with exact contract metadata and content receipts. Verification
checks both version and provenance; an unrelated same-version binary on `PATH`
does not satisfy the contract. Mutable vendor channels are limited to software
where prompt security updates are the explicit policy, such as Google Chrome.
