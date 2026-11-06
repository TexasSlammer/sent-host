# Upstream filing template

Use this only when the matrix shows behavior that is dangerous rather than merely divergent, and only through the disclosure channel the affected project documents. If the behavior is a plain spec violation with no security impact, a public issue is the right venue instead.

Rules I hold myself to before filing:

1. Re-run the matrix against the latest release of the affected client. A finding against an old version is not a finding.
2. Confirm the behavior outside the matrix with a minimal, copy-pasteable reproduction.
3. Say plainly what the behavior is and what it is not. If I could not turn it into an exploit, the filing says so.
4. Everything in the reproduction stays on loopback.

---

**Title:** one line: client, version, what it sends, and when.

**Affected version(s):** the version observed by the matrix and the latest release you re-verified on.

**Summary:** two sentences, no speculation. What goes on the wire and under which input.

**Observed behavior:** the exact matrix rows (case id, sent value, client version) and the minimal reproduction commands.

**Why it matters:** the security or correctness consequence, scoped honestly. Name the gate or parser that consumes the Host value and cite the spec section that defines what a valid authority is (RFC 3986 section 3.2, RFC 9110 section 7.4, WHATWG URL).

**Suggested behavior:** what the client should do instead and which spec line says so.

**Disclosure:** whatever the project's policy requires, followed.

**Filed:** link and date, once it exists.
