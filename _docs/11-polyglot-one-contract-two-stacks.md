---
title: "Polyglot: One Contract, Two Stacks"
order: 11
part: "Building It"
description: "Holding the Quarkus and Python implementations to the same AsyncAPI contract."
duration: "22 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain the trade-off between generating a model from a contract (`datamodel-codegen` on Python) and hand-keeping one against it (`HandlingEvent.java`), and which failure mode each mitigation is sized to catch.
- Write a conformance test for each strategy (a round-trip assertion for a generated model, an enum-membership assertion for a hand-kept one) that targets that strategy's own characteristic drift.
- Distinguish byte-identical frames from field-by-field agreement, and explain why `verify.sh`'s cross-stack check asserts the weaker, correct claim by design.
- Extend an `asyncapi diff -t breaking` CI gate with a `jq` filter so it catches payload-schema changes (an enum member removed) that the CLI's own classifier reports as `unclassified`.
- Decide when a drift gate across two independently-built stacks is worth its ongoing cost, and when one team holding the contract in their head is enough.

## Why this matters

Chapters 8 through 10 built the `handlingEvents` channel three times over: a Quarkus server, a Python server, and a client for each, all answering `contracts/asyncapi.yaml`'s one operation, `receiveHandlingEvent`. Each of those chapters stayed single-stack by choice: Chapter 8's Javadoc said so outright, choosing not to read Python syntax over a reader's shoulder while explaining WebSockets Next's lifecycle callbacks. This chapter is where that restraint pays off, by finally putting the two stacks side by side and asking the question the others deferred: given that nothing forces these two codebases to agree with each other, different languages, different frameworks, different teams in a real organization, why do they? The answer isn't discipline, and it isn't code review catching drift by inspection. It's two independent generation paths that both terminate at the same file, a cross-stack check that proves the wire frames actually match, and a CI gate that fails the build the moment they stop matching. `verify.sh` already runs all of this on every push; this chapter explains what it's checking and why the checks are shaped the way they are, including one real finding about the gate's own tooling that would otherwise let a breaking change through unnoticed.

## Two paths to the same shape

Neither stack treats `contracts/asyncapi.yaml` as documentation to read once and transcribe from memory. Both treat `components.schemas.HandlingEvent`, with `HandlingEventType`, `Location`, and `Money` pulled in by `$ref`, as the thing their own types have to answer to, continuously, and they answer to it by two different mechanisms with little in common beyond the file both start from.

The Python side generates. `scripts/extract-message-schema.py` inlines those three `$ref`s into one self-contained JSON Schema (Draft 2020-12), `build/handling-event.schema.json`, gitignored, rebuilt on every run, because `datamodel-code-generator`'s own AsyncAPI input support is unreliable against this document, but its JSON Schema input is not. `python/scripts/generate-models.sh` runs that extraction, then feeds the result to `datamodel-codegen --output-model-type pydantic_v2.BaseModel`, and what comes out the other end is `app/models_generated.py`: a `StrEnum` named `EventType` carrying the contract's eight members, and a `BaseModel` named `HandlingEvent` whose fields each carry the contract's own `pattern`, `description`, and `examples`: `constr(pattern=r'^evt_[0-9A-Za-z]{26}$')` for `eventId`, `AwareDatetime` for the two timestamps, `constr(pattern=r'^\d+\.\d{2}$') | None` for the optional `amount`. Nobody writes this file by hand, and nobody is supposed to: the generated header line says so, and `python/.gitignore` keeps it out of source control entirely, the same way `build/handling-event.schema.json` stays out.

The Quarkus side does the opposite: it hand-keeps. `HandlingEvent.java` is a plain Java record with the contract's nine fields in the contract's order, `@JsonInclude(NON_NULL)` so the two optional fields disappear from the wire rather than serializing as `null`, and a Javadoc comment that states the intent directly: "mirrors `components.schemas.HandlingEvent` in `contracts/asyncapi.yaml` field-for-field." `HandlingEventType.java` is a plain enum whose eight constant names are typed out to match the contract's `enum` list exactly, SCREAMING_SNAKE case included, because Jackson's default enum serialization is `Enum.name()` and matching the contract's spelling costs nothing beyond typing it correctly once. There's no generator step for this stack yet, `contracts/README.md` says so under "Generating stubs", which means "hand-kept to the contract" is a claim resting entirely on whoever wrote these two files having read the YAML correctly and never drifting from it afterward.

That asymmetry is not a Python-ahead, Quarkus-behind story. It's two different bets about where a contract-fidelity bug is most likely to be introduced, and two different mitigations sized to each bet. A generated model can't drift from the schema it was generated from: the failure mode moves upstream, to the generator's input (the extracted schema) or its own translation quirks (does `datamodel-codegen` render a `pattern` the way Pydantic actually enforces it?). A hand-kept record can drift any time someone edits it without re-reading the contract: the failure mode is squarely human, and it recurs on every future edit, not just the first one. `HandlingEventContractTest` exists precisely to catch the Quarkus-side failure mode the generation step on the Python side makes structurally impossible: it's a conformance test, not a generator, and it's the next thing this chapter covers.

{% include codetabs.html langs="Quarkus|Python" %}

```java
// examples/part3-handling-events/quarkus/src/main/java/.../HandlingEvent.java
// Hand-kept record — field order, names, and optionality all typed by
// hand against contracts/asyncapi.yaml's components.schemas.HandlingEvent.
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HandlingEvent(
        String eventId,
        String bookingId,
        String cargoId,
        HandlingEventType eventType,
        String location,
        Instant occurredAt,
        Instant registeredAt,
        String voyageNumber,
        String amount) {
}
```

```python
# examples/part3-handling-events/python/app/models_generated.py
# generated by datamodel-codegen:
#   filename:  handling-event.schema.json
# Nobody hand-edits this — regenerated by scripts/generate-models.sh on
# every build. Field order is alphabetical because that's the generator's
# default, not a choice anyone on this project made.
class HandlingEvent(BaseModel):
    amount: constr(pattern=r'^\d+\.\d{2}$') | None = Field(None, ...)
    bookingId: constr(pattern=r'^bkg_[0-9A-Za-z]{26}$') = Field(...)
    cargoId: constr(pattern=r'^crg_[0-9A-Za-z]{26}$') = Field(...)
    eventId: constr(pattern=r'^evt_[0-9A-Za-z]{26}$') = Field(...)
    eventType: EventType = Field(...)
    location: constr(pattern=r'^[A-Z]{2}[A-Z2-9]{3}$') = Field(...)
    occurredAt: AwareDatetime = Field(...)
    registeredAt: AwareDatetime = Field(...)
    voyageNumber: str | None = Field(None, ...)
```

{% include excalidraw.html file="11-contract-to-identical-frames" alt="A top box reads contracts/asyncapi.yaml, components.schemas.HandlingEvent, flowing down into extract-message-schema.py, which inlines the three dollar-ref'd schemas into build/handling-event.schema.json. From there an amber arrow labeled validates against points left to a Quarkus box describing a hand-kept HandlingEvent record and HandlingEventType enum checked by HandlingEventContractTest, and another amber arrow labeled generates from points right to a Python box describing datamodel-codegen producing app/models_generated.py, a Pydantic v2 model checked by test_contract.py. Both boxes feed downward into a bottom box reading verify.sh Step 3: cross-stack agreement, same eventId, eventType, bookingId, cargoId, location, occurredAt, and registeredAt values, noting that JSON key order differs between Jackson and Pydantic but is fine. A caption states two different mechanisms generate from or validate against the same file, and neither stack reads the other's source." caption="Figure 11.1: one contract reaches two stacks by two different mechanisms, and verify.sh proves they converge on the same frame." %}

## Converging on the same frame

Generation mechanism and conformance testing are both necessary but neither is, by itself, proof that the two running services agree. A generated Python model could still mis-serialize a field the generator mishandled; a hand-kept Quarkus record could still pass its own conformance test against the schema while differing from Python's interpretation of the same schema in some edge case neither test suite thought to check. `verify.sh` closes that gap the only way that actually closes it: by running both services, connecting to both, and comparing what came back.

Step 2 of `verify.sh` calls `run_stack_tests` against each stack in turn (`quarkus` at `localhost:8080`, `python` at `localhost:8081`), opening `{% raw %}ws://<target>/ws/v1/bookings/{bookingId}/handling-events{% endraw %}` with `websocat`, capturing the first pushed frame, and schema-validating it against the same extracted `build/handling-event.schema.json` both stacks' own test suites use. That alone proves each stack independently produces a contract-valid frame. It does not prove the two frames *agree* with each other, a schema permits a range of valid values, and two correct implementations could still diverge within that range (a different `location`, a different `eventType`) while both staying schema-valid. Step 3 is where `verify.sh` checks the thing a schema can't: it stashes every field from both captured frames into a bash associative array, `FRAME_FIELD["<stack> <field>"]`, and then loops over `eventId`, `eventType`, `bookingId`, `cargoId`, `location`, `occurredAt`, and `registeredAt`, asserting `FRAME_FIELD["quarkus $field"]` equals `FRAME_FIELD["python $field"]` for every one of them.

The comment directly above that loop names the one thing this comparison chose not to require: "parsed fields, not raw bytes; key order differs between Jackson and Pydantic, and that's fine." That's not a concession the test makes reluctantly; it's the correct level of strictness for what's actually being verified. JSON doesn't define a canonical key order, Jackson serializes a record's fields in declaration order, and Pydantic v2's generated model serializes in whatever order `datamodel-codegen` declared its fields, alphabetical, as it happens, because that's the generator's default and nobody asked it to do otherwise. Demanding byte-identical frames would mean coupling two independent serializers' internal field-ordering conventions to each other for no behavioral gain; demanding field-by-field value agreement is exactly the claim "one contract, two stacks" is making, and it's the claim this comparison actually tests.

## The conformance tests, side by side

Each stack also carries its own conformance test, and the two tests ask slightly different questions because they're guarding against each stack's own characteristic failure mode. `HandlingEventContractTest` (plain JUnit, no `@QuarkusTest`, because it's exercising record serialization, not a running endpoint) loads the shared fixture from the classpath, serializes each event the way the running application would, and validates the result against the extracted schema: catching the case where `HandlingEvent.java` has silently drifted from `components.schemas.HandlingEvent` since the last time someone checked by eye. It also asserts `HandlingEventType.values().length == 8` and that the names match the contract's enum list in order, which is the hand-kept side's specific risk: an enum member added, removed, or renamed without the contract changing to match, or vice versa.

`test_contract.py` runs the generated model through a different question, because "does the model match the schema" is structurally guaranteed by the generation step; what it checks instead is round-tripping: does `HandlingEvent.model_validate(raw)` followed by `model.model_dump_json(exclude_none=True)` reproduce the fixture's exact values, not just "still valid JSON"? That test's docstring calls out a specific, easy-to-miss failure mode it protects against: Pydantic v2 preserves a timestamp's original `Z` UTC suffix on serialization rather than normalizing it to `+00:00`, and a less careful round-trip assertion (`assert dumped["occurredAt"] is not None`, say) would pass even if that normalization silently happened. Both test files check conformance to the one contract; neither one is redundant with the other, because they're defending against the two stacks' two different ways of getting there.

{% include codetabs.html langs="Quarkus|Python" %}

```java
// HandlingEventContractTest.java — guards the hand-kept side's specific risk
@Test
void handlingEventTypeHasAllEightContractMembers() {
    List<String> contractMembers = List.of(
            "HANDLING_EVENT_TYPE_UNSPECIFIED", "RECEIVE", "LOAD", "UNLOAD",
            "CUSTOMS", "CLAIM", "HOLD", "DELIVERED");
    HandlingEventType[] actual = HandlingEventType.values();
    assertEquals(8, actual.length, "HandlingEventType must have exactly 8 members");
    assertEquals(contractMembers,
            Arrays.stream(actual).map(Enum::name).toList(),
            "HandlingEventType members must match the contract's enum, in order");
}
```

```python
# test_contract.py — guards the generated side's specific risk: round-trip fidelity
def test_generated_model_round_trips_fixture_values_exactly() -> None:
    for raw in load_fixture():
        model = HandlingEvent.model_validate(raw)
        dumped = json.loads(model.model_dump_json(exclude_none=True))
        assert dumped == raw, f"round-trip drift for {raw['eventId']}: {dumped} != {raw}"
```

## The drift gate: making "one contract" enforceable

Everything so far, two generation paths, a shared conformance schema, a cross-stack field comparison, is still something a developer has to remember to run. `.github/workflows/contracts.yml` is what turns "one contract" from a convention a careful team follows into a property CI enforces on every push and every pull request, across four jobs that each check a different way the contract or its implementations could drift.

`validate` is the cheapest check: `npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml` against the file as it stands, catching a malformed document before anything downstream wastes time on it. `drift` is the job this chapter has mostly already described without naming it: extract the schema, run `generate-models.sh` to regenerate the Python model from scratch, then run both `HandlingEventContractTest` and `test_contract.py`; if either stack's hand-kept or generated code has drifted from a contract edit in this same PR, one of those conformance tests fails here, before `examples` ever spins up a container. `examples` is the live-wire check: `discover-examples` builds a matrix from every `examples/*/verify.sh` on disk, and `examples` runs each one (`compose up`, connect, assert, `compose down`) with three retries to absorb CI flakiness without masking a real, repeatable failure.

`breaking` is the job worth slowing down for, because it contains a finding this project didn't expect going in. The naive approach is to lean entirely on the AsyncAPI CLI's own classification: run `asyncapi diff old.yaml new.yaml -t breaking`, and if it reports anything, fail. Verified locally against this exact contract, that approach has a real gap. Removing `HOLD` from `HandlingEventType`'s `enum` list, a textbook breaking change, since any client or server already depending on that member now can't, produces this from `-t breaking`:

```bash
$ npx -y @asyncapi/cli@6.2.1 diff main.yaml edited.yaml -t breaking -f json
[]
```

Zero. The CLI's `-t all` output tells you why: every change the enum removal produces, six `remove`/`edit` pairs, one per place the contract's `$ref` chain repeats `HandlingEventType`'s `enum` (the schema itself, the message payload, the operation, the channel), carries `"type": "unclassified"`, not `"type": "breaking"`. The CLI's structural classifier covers channel, operation, and server-level edits well; it doesn't commit to a verdict on payload-schema content. A gate that only asked `-t breaking` would have let that enum removal merge clean.

That's why `breaking` runs `-t all` and applies its own jq filter on top, rather than trusting the CLI's classification alone:

```bash
jq '[.changes[]? | select(
    .type == "breaking" or
    .action == "remove" or
    (.action == "edit" and (.path | test("/(type|pattern)$"))) or
    (.action == "add" and (.path | test("/required/[0-9]+$")))
  )]' diff.json
```

Anything the CLI itself calls `"breaking"` still counts. On top of that: any `remove` at all (an enum member, a property, anything), any `edit` that lands on a `type` or `pattern` key (a field retyped, a regex loosened or tightened), and any `add` that lands inside a `required` array (a field that used to be optional becoming mandatory, which breaks every client that was correctly omitting it). A purely additive change, a new optional field, a new enum member appended, shows up as an `add` to `properties` or to the end of an `enum` array, matches none of those four conditions, and passes. Against the `HOLD` removal, that filter catches exactly the six `remove` entries the structural classifier missed:

```bash
$ jq '[.changes[]? | select(.type == "breaking" or .action == "remove" or
    (.action == "edit" and (.path | test("/(type|pattern)$"))) or
    (.action == "add" and (.path | test("/required/[0-9]+$"))))] | length' diff.json
6
```

Six, not zero. That's the gap between the two approaches on this exact contract, measured, not assumed.

{% include excalidraw.html file="11-drift-gate-pipeline" alt="A PR editing contracts/asyncapi.yaml fans out with four arrows to four jobs: validate, running asyncapi validate; breaking, running asyncapi diff dash t all plus a jq filter for remove, edit of type or pattern, and add to required; drift, which extracts the schema, regenerates the Python model, and runs both conformance tests; and examples matrix, which runs verify.sh per discovered example with three retries. All four jobs feed into an examples-summary gate box asking whether all four are green. An amber arrow labeled all green leads right to a merge-allowed box; a dashed arrow labeled any red leads down to a gate-fails box. A caption states that asyncapi diff's own dash t breaking classification misses payload-schema changes, so the breaking job's jq filter closes that gap itself." caption="Figure 11.2: the drift gate: four independent checks, and a merge only happens when all four agree the contract still holds." %}

## When polyglot-by-contract is worth it (and when it isn't)

None of this infrastructure is free. A dedicated extraction script, a second generation pipeline, two conformance test suites with slightly different assertions, a four-job CI workflow, and a jq filter someone has to understand well enough to extend when a fifth kind of breaking change shows up later: that's real, ongoing cost, paid on every contract edit, not a one-time setup fee. It's worth paying when the thing it buys is actually needed: independent teams or independent deploy cadences on each stack, where "read the other team's source to stay in sync" isn't a realistic substitute for an automated check; a domain where a silently broken client is expensive enough, billing, compliance, anything audited, that catching drift in a PR beats catching it in production; or, as in this project specifically, a teaching site whose entire premise is that the same contract produces interchangeable implementations, which is a claim nobody should take on faith from prose alone.

It's not worth paying for a single-stack project: there's nothing to drift apart from. It's also arguably not worth it for two stacks maintained by the same one or two people who already hold the whole contract in their heads and feel every edit land in both places as they make it; at that scale, the gate mostly re-proves something the author already knows, at the cost of CI minutes and a workflow file someone still has to maintain. The signal that it's time to add this kind of gate is organizational, not technical: the moment the person editing the contract and the person who'll find out their code broke are no longer guaranteed to be the same person, a second team picks up the Python service, a contributor sends a PR against just one stack, the contract gets reviewed by someone who's never opened the generator script, is the moment "I'll remember to keep both stacks in sync" stops being a credible plan, and an automated gate replaces trust with a specific, auditable answer about whether the contract still holds.

## On the wire

Connecting to both stacks and capturing the first pushed frame, the `RECEIVE` event, `fixtures/handling-events.json[0]`, shows exactly what `verify.sh` Step 3 compares and exactly what it doesn't. Quarkus, via Jackson, serializes `HandlingEvent`'s record fields in their declared order:

```json
{"eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
```

Python, via Pydantic's generated model, serializes in the field order `datamodel-codegen` chose, alphabetical, with `voyageNumber` and `amount` dropped by `exclude_none=True` the same way Quarkus drops them via `@JsonInclude(NON_NULL)`:

```json
{"bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
```

`eventId` first versus `bookingId` first: two different, equally valid serializations of the same seven fields and seven identical values. That's `verify.sh`'s Step 3 assertion made concrete: byte-for-byte these frames differ in the second character; field-by-field they're the same event.

The drift gate's failure mode is just as concrete. Deleting the `- HOLD` line from `contracts/asyncapi.yaml`'s `HandlingEventType.enum` and diffing against the unmodified file reproduces exactly the finding described above: `asyncapi diff -t breaking` reports `[]`, nothing to see; `asyncapi diff -t all` reports six changes, every one `"type": "unclassified"`; and the gate's own jq filter, run against that same `-t all` output, isolates the six `remove` actions and fails the job. Locally, the same sequence `breaking` runs in CI:

```bash
npx -y @asyncapi/cli@6.2.1 diff /tmp/asyncapi.main.yaml contracts/asyncapi.yaml \
  -t all -f json > /tmp/asyncapi.diff.json
jq '[.changes[]? | select(
    .type == "breaking" or
    .action == "remove" or
    (.action == "edit" and (.path | test("/(type|pattern)$"))) or
    (.action == "add" and (.path | test("/required/[0-9]+$")))
  )]' /tmp/asyncapi.diff.json
```

To reproduce the full gate, including the parts the `breaking` job doesn't cover, run it the way `drift` and `examples` do, from the repo root:

```bash
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json
(cd examples/part3-handling-events/python && ./scripts/generate-models.sh)
(cd examples/part3-handling-events/quarkus && ./mvnw -B test -Dtest=HandlingEventContractTest)
(cd examples/part3-handling-events/python && uv run pytest tests/test_contract.py -v)
bash examples/part3-handling-events/verify.sh
```

The last line is the one that also exercises the cross-stack comparison and the reconnect check: everything this chapter has walked through, in the order `verify.sh` actually runs it, against two real running containers rather than two descriptions of what they're supposed to do.

## Where this goes next

Part 3 ends here having built the thing its title promised: one `HandlingEvent` channel, running on two independently generated stacks, provably agreeing on every field of every frame, with a CI gate that keeps that agreement true as the contract keeps changing. Part 4, "Production Concerns," picks up exactly where this fixture-replay example leaves off. Chapter 12 comes back to backpressure from the server side: what happens when a server's own outbound buffer toward a slow client backs up, the mirror image of the bounded client-side queue Chapter 10 built. Chapter 13 gives this channel's error paths the full treatment Chapter 9 only touched with one `1008` close code. Chapters 15 and 16 pick the stateless-reconnect limitation both clients disclosed back up as a formal topic, ending in a Kafka-backed feed that lets a reconnecting client resume from an offset instead of accepting whatever gap a disconnect left. None of those chapters get to assume a single-stack world either, every one of them lands against both the Quarkus and Python implementations this chapter just proved agree, and the same drift gate keeps checking that they still do.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>"One contract, two stacks" is a property this project enforces with three independent mechanisms layered on top of each other, not a single trick: Python generates its model from the contract so drift there would require the generator itself to misbehave; Quarkus hand-keeps its record and enum and catches drift with <code>HandlingEventContractTest</code>, a test specifically aimed at the hand-kept side's own failure mode; and <code>verify.sh</code> connects to both running services and asserts field-by-field agreement on the frames they actually emit, comparing parsed values rather than raw bytes because JSON key order is not and should not be part of the contract. None of that is aspirational: <code>.github/workflows/contracts.yml</code>'s four jobs (<code>validate</code>, <code>breaking</code>, <code>drift</code>, <code>examples</code>) run it on every push, and the <code>breaking</code> job specifically does not trust the AsyncAPI CLI's own <code>-t breaking</code> classifier alone, because a verified local test against this exact contract showed it reports zero changes for an enum-member removal that is unambiguously a breaking change; the job's own jq filter, checking for any <code>remove</code>, any <code>edit</code> of a <code>type</code> or <code>pattern</code>, or any <code>add</code> to a <code>required</code> array, catches what the CLI's structural classifier was never built to see in a payload schema. Reach for this much machinery when independent teams, independent deploy cadences, or a cost-of-being-wrong high enough to matter mean nobody can be trusted to notice drift by reading diffs; skip most of it when one person already holds the whole contract in their head and the gate would mostly be re-proving what they already know.</p></div>

## Build, run, observe

```bash
cd examples/part3-handling-events && ./verify.sh
```

Brings up both the Quarkus and the Python stack over Docker Compose and replays the same deterministic three-event fixture through each, asserting every field against the fixture and against the contract-derived JSON Schema. It prints PASS once every assertion holds on both stacks; see `examples/part3-handling-events/README.md` for full output.

## For deeper coverage

- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): the contract-ownership and schema-evolution patterns behind holding two independently-generated stacks to one source document.
- J. Higginbotham, *Principles of Web API Design* (Addison-Wesley, 2021): governance practices for a contract multiple teams or stacks consume, the organizational case for the drift gate this chapter builds.
- *Cloud Native Design Patterns*, "API Registry" chapter: one authoritative, versioned home for a contract with compatibility rules gating breaking changes in CI, the same role the `breaking` job plays here for `asyncapi.yaml`.
- *Cloud Native Design Patterns*, "Protocols in Depth" chapter: the wire-format reasoning behind why field-by-field agreement, not byte-identical output, is the correct claim to assert across two serializers.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `components.schemas`, `$ref`, and operation shapes both generation paths in this chapter read from.
- [JSON Schema](https://json-schema.org/): the Draft 2020-12 vocabulary `extract-message-schema.py` emits and both `datamodel-codegen` and the hand-kept Quarkus conformance test validate against.
