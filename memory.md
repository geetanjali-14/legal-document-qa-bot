# MEMORY.md

> Default operating rules for all coding tasks.
> Follow project-specific instructions when they are more specific.

## 1. PRIORITY

When rules conflict, use this order:

1. Correctness
2. Security
3. Existing architecture
4. Backward compatibility
5. Maintainability
6. Testability
7. Performance
8. Simplicity

---

## 2. WORKFLOW

**Understand → Plan → Implement → Verify → Review**

### UNDERSTAND

* Inspect before editing.
* Read the relevant code and execution flow.
* Search before creating.
* Reuse existing code before adding new code.
* Identify affected callers, interfaces, tests, configuration, and dependencies.
* Follow existing project conventions.

### PLAN

* Define the smallest change that solves the requirement.
* Preserve existing behavior unless change is required.
* Avoid unrelated refactoring.
* Resolve high-impact ambiguity before coding.
* Prefer the simplest maintainable solution.

### IMPLEMENT

* Keep changes focused and minimal.
* Follow existing architecture and patterns.
* Keep responsibilities separated.
* Prefer clear code over clever code.
* Prefer reuse over duplication.
* Avoid unnecessary abstractions.
* Avoid unnecessary dependencies.
* Validate data at system boundaries.
* Handle expected failure cases.

### VERIFY

* Run focused tests first.
* Run related tests/checks next.
* Run lint/type checks when applicable.
* Verify important user flows when needed.
* Fix failures before completion.

### REVIEW

Before finishing, confirm:

* Requirement is satisfied.
* Change is minimal.
* Existing behavior is preserved.
* Edge cases are handled.
* Errors are handled.
* Security is preserved.
* No unnecessary files/dependencies changed.
* Relevant verification was performed.

---

## 3. CODING

* Match existing project style.
* Keep functions/classes focused.
* Keep interfaces explicit.
* Prefer readable names.
* Avoid premature optimization.
* Avoid speculative features.
* Avoid changing working code without reason.
* Comments should explain **why**, not obvious **what**.
* Remove obsolete code/comments when behavior changes.

---

## 4. INPUT & ERRORS

* Treat external input as untrusted.
* Validate at boundaries.
* Handle null, empty, invalid, and boundary values.
* Never silently swallow errors.
* Preserve useful error context.
* Return appropriate errors/status codes.
* Never expose internal details or secrets.

---

## 5. SECURITY

* Never hardcode secrets.
* Never commit credentials, tokens, or private keys.
* Never log secrets or sensitive data.
* Respect authentication and authorization.
* Follow least privilege.
* Protect against injection and unsafe input.
* Do not disable security controls to make code work.

---

## 6. DATABASE & API

* Understand existing schemas/contracts before changing them.
* Avoid unnecessary database/network calls.
* Preserve data integrity.
* Consider transactions/concurrency when relevant.
* Preserve API compatibility unless breaking change is required.
* Validate requests and handle external failures.

---

## 7. DEBUGGING

When something fails:

1. Reproduce.
2. Read the complete error.
3. Trace the failure.
4. Inspect inputs/outputs.
5. Form a hypothesis.
6. Verify the hypothesis.
7. Fix the root cause.
8. Run regression checks.

**Never make random changes until the error disappears.**

---

## 8. DECISIONS

* Existing implementation → reuse it.
* Existing convention → follow it.
* Unsure whether something exists → search first.
* Low-risk ambiguity → choose the simplest reasonable option.
* Security/data/architecture ambiguity → ask.
* Two valid solutions → choose the simpler maintainable one.
* New dependency → justify it first.
* Refactor → only when necessary for the task.

---

## 9. AGENT TRUTHFULNESS

Never claim something was:

* Run when it was not run.
* Tested when it was not tested.
* Fixed when it was not verified.
* Created when it does not exist.
* Changed externally when it was not changed.

Clearly distinguish:

**Verified / Assumed / Not Tested / Blocked**

---

## 10. COMPLETION

A task is complete only when:

**Implement → Verify → Review → Report**

Never stop at "code written."

Report:

* What changed.
* What was verified.
* Any remaining issues.
* Anything that could not be verified.

