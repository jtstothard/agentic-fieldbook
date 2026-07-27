# Severity Rubric — Reviewer Calibration

Binding severity classification for all reviewer calibration runs under the agentic operating system.

## Why this exists

Without a shared rubric, reviewers calibrate severity idiosyncratically — flattening critical→major and escalating minor→major. With this rubric bound into the dispatch prompt, severity classification is consistent and lanes can be truly calibrated.

## Severity definitions (binding)

Reviewers MUST classify each finding using exactly these definitions. Do not invent intermediate levels.

### CRITICAL
A defect that is **directly exploitable or causes immediate harm** without further precondition. One of:
- Remote code execution, SQL injection, auth bypass, privilege escalation.
- Plaintext/secret/credential exposure to an attacker or to logs accessible to an attacker.
- Cryptographic failure that breaks confidentiality or integrity of protected data (e.g. static IV, weak key derivation, disabled signature verification).
- Data loss or corruption that is non-recoverable and affects persisted state.
- A service-level failure that takes a production path fully offline or causes cascading outage.

Rule of thumb: *if an attacker or a single bad request can weaponize it, it's critical.*

### MAJOR
A defect that **breaks correct behavior, security posture, or operational correctness** but is not directly weaponizable on its own, or requires a precondition to cause harm. One of:
- Logic error producing wrong outputs for valid inputs.
- Missing input validation that allows malformed/boundary data through (but not a direct injection/RCE path).
- Insecure default that weakens security but is not an active exploit (e.g. public-read ACL on objects, container running as root without escape).
- Missing error handling that causes unhandled 500s or crashes on expected-but-edge inputs.
- Resource misconfiguration that risks instability under load (e.g. no resource limits, mutable tags).
- IDOR/enumeration paths that leak data to an authenticated user but are not fully unauthenticated.

Rule of thumb: *the code is wrong and will cause real problems, but an attacker can't trivially own the system with it.*

### MINOR
A defect that is **cosmetic, edge-case, or a contract/quality issue** with no direct security or correctness impact in normal operation. One of:
- Off-by-one or timezone assumption that only affects unusual inputs.
- Style/naming/readability issue that does not change behavior.
- Documentation drift or missing docstring where behavior is otherwise correct.
- Edge case (empty input, zero value, unicode) handled imperfectly but without crash or data issue.
- Non-idiomatic but functionally correct code.

Rule of thumb: *worth fixing, but a reviewer would not block a merge on it.*

## Classification rules

1. **Severity is about the defect's real-world impact, not its line count or obviousness.** A one-line static IV is critical; a fifty-line refactor is minor if it changes nothing behaviorally.
2. **Classify the defect as it would behave in production, not in the test/example context.** Assume the code is deployed as written.
3. **When in doubt between two levels, choose the higher severity** and state the uncertainty in the finding's confidence field. Do not silently downgrade.
4. **Confidence is separate from severity.** Confidence = how sure you are the defect is real. Severity = how bad it is if real.
5. **One severity per finding.** If a finding spans multiple severities, split it into separate findings.

## Worked examples (for calibration)

| Defect | Correct severity | Common mislabel | Why |
|---|---|---|---|
| JWT `none` algorithm in allowlist | **critical** | major | Auth bypass — attacker can forge tokens. Directly weaponizable. |
| Static IV in AES encryption | **critical** | major | Breaks confidentiality — identical plaintexts produce identical ciphertexts. Cryptographic failure. |
| SQL injection via string concatenation | **critical** | major | Direct RCE-equivalent data exposure. |
| Container runs as root | **critical** | major | Privilege-escalation primitive; standard critical-severity finding. |
| IDOR via unvalidated user ID | **major** | critical | Authenticated path, requires valid session. Real but not unauthenticated. |
| S3 default ACL public-read | **major** | critical | Insecure default, but not an active exploit. |
| Payment zero/negative amount accepted | **major** | minor | Functional break with real financial impact, but not a security exploit. |
| Date parsing assumes UTC | **minor** | major | Edge-case correctness on unusual inputs, no security/crash impact. |
| Mutable `latest` tag without digest pinning | **major** | minor | Operational risk under real deployment. |
| Over-flagging a REST style debate | **(no finding)** | minor | Ambiguous design choices are not defects. Use `uncertain` disposition. |

## Reviewer prompt addendum (to be appended to all future review dispatches)

> **Severity classification is mandatory and binding.** Classify each finding as `critical`, `major`, or `minor` strictly per the Severity Rubric (see `review-calibration/references/severity-rubric.md`). When uncertain between two levels, choose the higher and flag confidence. Do not invent intermediate severities. A one-line crypto defect is critical; a style nit is minor — severity tracks real-world impact, not line count.