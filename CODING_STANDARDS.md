# Coding Standards

## Testing

### Core Principle

Tests verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't break unless behavior changed.

### Good Tests

Integration-style tests that exercise real code paths through public APIs. They describe _what_ the system does, not _how_.

- Test behavior users/callers care about
- Use the public API only
- Survive internal refactors
- One logical assertion per test

### Bad Tests

Red flags:

- Mocking internal collaborators (your own classes/modules)
- Testing private methods
- Asserting on call counts/order of internal calls
- Test breaks when refactoring without behavior change
- Test name describes HOW not WHAT
- Verifying through external means (e.g. querying a DB) instead of through the interface

### What Tests Never Check

**Never the wording of documentation** (README, AGENTS.md, ADRs, GLOSSARY.md). An acceptance criterion "the docs name X" is met by updating the docs, not by a test.

- Bad: `assert "ArticleMonitor" in Path("README.md").read_text()`
- Good: no test; the commit updates the docs.

**Never source code** (template markup, JS expressions, Python AST). Exceptions: import-graph guards and lint-style rules over _all_ files of a kind.

- Bad: `assert "display: none" in Path("static/css/app.css").read_text()`
- Good: render the page and assert on what the user gets, e.g. the element is missing from the response.

**Never expected values from the module under test.** Take them from a fixed literal, a worked example or a spec, not from the module's constants or calculations.

- Bad: `assert result == MAX_RETRIES` with `MAX_RETRIES` imported from the module, or an expected value recomputed with the module's own helper.
- Good: `assert result == 3`, with the 3 taken from the spec.

Enum members (e.g. a status enum) are fine as expected values when the test checks _which_ state results; they name the state, they don't compute it. Where the stored spelling itself is the promise (an export, an API contract), expect the literal.

**Never the absence of fields or methods.** Removed code is gone; a test for `not hasattr(Article, "title")` guards nothing a caller can observe.

- Bad: `assert not hasattr(Article, "title")`
- Good: no test; if the removal changes behaviour, test the behaviour.

### Mocking

Mock at **system boundaries** only:

- External APIs (llm-provider, email, etc.)
- Time/randomness
- File system or databases when a real instance isn't practical

**Never mock your own classes/modules or internal collaborators.** If something is hard to test without mocking internals, redesign the interface.

Prefer SDK-style interfaces over generic fetchers at boundaries — each function is independently mockable with a single return shape, no conditional logic in test setup.

### TDD Workflow: Vertical Slices

Do NOT write all tests first, then all implementation. That produces tests that verify _imagined_ behavior and are insensitive to real changes.

Correct approach — one test, one implementation, repeat:

```
RED→GREEN: test1→impl1
RED→GREEN: test2→impl2
RED→GREEN: test3→impl3
```

Each test responds to what you learned from the previous cycle. Never refactor while RED — get to GREEN first.

## Interface Design

### Deep Modules

Prefer deep modules: small interface, deep implementation. A few methods with simple params hiding complex logic behind them.

Avoid shallow modules: large interface with many methods that just pass through to thin implementation. When designing, ask: can I reduce the number of methods? Can I simplify the parameters? Can I hide more complexity inside?

### Design for Testability

1. **Accept dependencies, don't create them** — pass external dependencies in rather than constructing them internally.
2. **Return results, don't produce side effects** — a function that returns a value is easier to test than one that mutates state.
3. **Small surface area** — fewer methods = fewer tests needed, fewer params = simpler test setup.
