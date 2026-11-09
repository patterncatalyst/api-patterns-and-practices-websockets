---
title: "Polyglot: One Contract, Two Stacks"
order: 11
part: "Building It"
description: "Holding the Quarkus and Python implementations to the same AsyncAPI contract with generation, conformance tests and a CI drift gate."
duration: "22 min read"
---

## Learning objectives

By the end of this chapter you can:

- Choose between generating a model from a contract and hand-keeping one against it, and name the drift each one risks.
- Write a conformance test for each strategy: a round-trip assertion for a generated model, an enum-membership assertion for a hand-kept one.
- Compare two stacks' frames field by field instead of byte by byte.
- Extend an `asyncapi diff` CI gate with a `jq` filter so it catches payload-schema changes the CLI reports as `unclassified`.
- Decide when a drift gate across two stacks is worth its cost.

## Why this matters

The `handlingEvents` channel runs on a Quarkus server and a Python server, both answering the one operation `receiveHandlingEvent` in `contracts/asyncapi.yaml`. Nothing forces two codebases in two languages, possibly owned by two teams, to agree. Three mechanisms do: each stack ties its types to the same file, a cross-stack check compares the frames the running services emit, and a CI gate fails the build when the contract changes in a way that breaks a client.

## Two paths to the same shape

Both stacks treat `components.schemas.HandlingEvent`, with `HandlingEventType`, `Location` and `Money` pulled in by `$ref`, as the thing their types answer to. They get there differently.

**Python generates.** `scripts/extract-message-schema.py` inlines the three `$ref`s into one self-contained JSON Schema (Draft 2020-12), `build/handling-event.schema.json`, which is gitignored and rebuilt on every run. `datamodel-code-generator` is unreliable on the AsyncAPI document itself but reliable on JSON Schema. `python/scripts/generate-models.sh` feeds the extracted schema to `datamodel-codegen --output-model-type pydantic_v2.BaseModel` and writes `app/models_generated.py`: a `StrEnum` with the contract's eight members and a `HandlingEvent` model whose fields carry the contract's patterns (`^evt_[0-9A-Za-z]{26}$` for `eventId`, `AwareDatetime` for the timestamps). The file is gitignored and never edited by hand. Field order is alphabetical, the generator's default.

**Quarkus hand-keeps.** `HandlingEvent.java` is a record with the contract's nine fields in the contract's order. `@JsonInclude(NON_NULL)` drops the two optional fields from the wire instead of serializing `null`. `HandlingEventType.java` is an enum whose eight constants are typed to match the contract's `enum` list, because Jackson serializes an enum with `Enum.name()`. No generator step exists for this stack (`contracts/README.md` says so under "Generating stubs"), so fidelity rests on whoever edits the two files.

```java
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

The two strategies carry different risks, and each gets a mitigation sized to its own:

| | Generated (Python) | Hand-kept (Quarkus) |
|---|---|---|
| Drifts from the schema | Cannot, by construction | On any edit made without rereading the contract |
| Risk moves to | The generator's input and its translation quirks | The person editing |
| Conformance test checks | Round trip: parse a fixture, dump it, get the same values | Serialized frames validate; enum members match the contract in order |

## Converging on the same frame

Neither mitigation proves the two running services agree. A schema permits a range of valid values, and two correct implementations can differ inside it (a different `location`, a different `eventType`) while both stay schema-valid. Proving agreement means running both stacks (Quarkus on `localhost:8080`, Python on `localhost:8081`), opening {% raw %}`ws://<target>/ws/v1/bookings/{bookingId}/handling-events`{% endraw %} on each with `websocat`, validating the first pushed frame from each against the extracted schema, and then comparing `eventId`, `eventType`, `bookingId`, `cargoId`, `location`, `occurredAt` and `registeredAt` across the two frames, one field at a time.

The comparison is on parsed fields, not bytes. JSON defines no canonical key order. Jackson writes a record's fields in declaration order and the generated Pydantic model writes them alphabetically. Both drop the absent `voyageNumber` and `amount`, Quarkus through `@JsonInclude(NON_NULL)` and Python through `exclude_none=True`. The first `RECEIVE` frame from each:

```json
{"eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
{"bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
```

Byte-identical frames would couple two serializers' internal ordering for no behavioral gain. Field agreement is the claim "one contract, two stacks" makes.

{% include excalidraw.html file="11-contract-to-identical-frames" alt="The contract flows through a schema extraction step to two boxes: a hand-kept Quarkus record checked by a conformance test, and a generated Python model checked by its own. Both feed a cross-stack comparison of field values, where JSON key order may differ." caption="Figure 11.1: One contract reaches two stacks by two mechanisms, and a field-by-field comparison proves they emit the same frame." %}

## Conformance tests, side by side

Each stack tests the failure mode its strategy allows. The Quarkus test is plain JUnit (no running endpoint). It serializes the fixture events the way the application does, validates them against the extracted schema, and pins the enum to the contract:

{% include codetabs.html langs="Quarkus|Python" %}

```java
    @Test
    void handlingEventTypeHasAllEightContractMembers() {
        List<String> contractMembers = List.of(
                "HANDLING_EVENT_TYPE_UNSPECIFIED", "RECEIVE", "LOAD", "UNLOAD",
                "CUSTOMS", "CLAIM", "HOLD", "DELIVERED");

        HandlingEventType[] actual = HandlingEventType.values();
        assertEquals(8, actual.length, "HandlingEventType must have exactly 8 members");

        List<String> actualNames = Arrays.stream(actual).map(Enum::name).toList();
        assertEquals(contractMembers, actualNames,
                "HandlingEventType members must match the contract's enum, in order");
    }
```

```python
def test_generated_model_round_trips_fixture_values_exactly() -> None:
    for raw in load_fixture():
        model = HandlingEvent.model_validate(raw)
        dumped = json.loads(model.model_dump_json(exclude_none=True))
        assert dumped == raw, f"round-trip drift for {raw['eventId']}: {dumped} != {raw}"
```

For the generated model, "matches the schema" is guaranteed by generation, so the round trip checks what generation can get wrong: the dumped values must equal the fixture exactly, not merely stay valid JSON. Pydantic v2 keeps a timestamp's `Z` suffix on output instead of normalizing it to `+00:00`, and a weaker assertion would not notice if that changed.

## The drift gate

`.github/workflows/contracts.yml` makes the contract a property CI enforces on every push and pull request, in four jobs:

| Job | Checks |
|---|---|
| `validate` | `asyncapi validate contracts/asyncapi.yaml` rejects a malformed document first |
| `drift` | Extracts the schema, regenerates the Python model, runs both conformance tests |
| `examples` | Runs every `examples/*/verify.sh` in a matrix, with three retries for CI flakiness |
| `breaking` | Diffs the contract against `main` and fails on a breaking change |

`breaking` does not trust the AsyncAPI CLI's classifier. Removing `HOLD` from `HandlingEventType`'s `enum` is a breaking change, because any client that depends on that member now fails, yet:

```bash
$ npx -y @asyncapi/cli@6.2.1 diff main.yaml edited.yaml -t breaking -f json
[]
```

With `-t all`, the same edit yields six `remove` and `edit` entries, one for each place the `$ref` chain repeats the enum (schema, message payload, operation, channel), all typed `unclassified`. The CLI classifies channel, operation and server edits and commits to no verdict on payload-schema content. So the job runs `-t all` and applies its own filter:

```bash
            breaking="$(jq '[.changes[]? | select(
                .type == "breaking" or
                (.action == "remove" and ((.path | test("/const$")) | not)) or
                (.action == "edit" and (.path | test("/(type|pattern)$"))) or
                (.action == "add" and (.path | test("/required/[0-9]+$")))
              )]' /tmp/asyncapi.diff.json)"
```

It fails on anything the CLI calls breaking, any `remove`, any `edit` of a `type` or `pattern` key (a field retyped, a regex changed), and any `add` inside a `required` array (an optional field becoming mandatory breaks every client that omitted it). A new optional property or an enum member appended at the end matches none of these and passes. The `/const` exclusion covers one safe case: widening a `const` to an `enum` that still contains the old value. The CLI models that as a `remove` of `/const` plus an `add` of `/enum`, and every value the old constraint accepted is still accepted.

{% include excalidraw.html file="11-drift-gate-pipeline" alt="A pull request that edits the contract fans out to four jobs: validate, breaking, drift and an examples matrix. A merge is allowed only when all four are green; any red job blocks the merge." caption="Figure 11.2: Four independent checks gate a contract change, and a merge needs all four green." %}

## When a drift gate pays

The drift gate costs an extraction script, a generation pipeline, two conformance test sets, a four-job workflow and a `jq` filter that someone has to extend when a fifth kind of breaking change appears. Pay it when:

- the stacks have different teams or deploy cadences, so reading the other source is not a realistic check;
- a client breaking unnoticed is expensive (billing, compliance, anything audited);
- the claim that one contract yields interchangeable implementations needs evidence, not prose.

Skip it for a single-stack project, which has nothing to drift against, and for two stacks kept by one or two people who hold the whole contract in their heads. The trigger is organizational: when the person editing the contract is no longer the person who finds out their code broke, "I'll remember to update both" stops being a plan.

> **Decision**
>
> Tie each stack to the contract in the way that fits it: generate the model where a generator works, hand-keep it with a conformance test where it does not. Compare running services field by field, never byte by byte. Gate every contract change with `asyncapi diff -t all` plus a `jq` filter, because `-t breaking` misses payload-schema changes. Add the whole apparatus when independent teams, independent deploys or the cost of a silent break mean nobody will catch drift by reading diffs.

> **🤖 Explore with your agent**
>
> "In `contracts/asyncapi.yaml`, remove `HOLD` from `HandlingEventType`. Run `asyncapi diff -t breaking -f json` and `-t all -f json` against the unmodified file, then run the `jq` filter from the `breaking` job in `.github/workflows/contracts.yml` on the `-t all` output. Report how many changes each step finds and which of the two would let the removal merge."
>
> Check: `-t breaking` prints `[]`, the filter finds six entries.

## Build, run, observe

From the repository root:

```bash
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json
(cd examples/part3-handling-events/python && ./scripts/generate-models.sh)
(cd examples/part3-handling-events/quarkus && ./mvnw -B test -Dtest=HandlingEventContractTest)
(cd examples/part3-handling-events/python && uv run pytest tests/test_contract.py -v)
bash examples/part3-handling-events/verify.sh
```

`verify.sh` starts both stacks with Docker Compose, replays the same three-event fixture through each, checks every field against the fixture and the extracted schema, compares the two stacks' first frames, then forces a client reconnect. It prints `PASS: ` when every check holds. `examples/part3-handling-events/README.md` has the full output.

- Delete the `- HOLD` line from the contract's `HandlingEventType.enum` and diff against the unmodified file with `-t breaking`, then `-t all` plus the filter: the first reports nothing, the second reports six changes and the job fails.
- Add a ninth constant to `HandlingEventType.java` without touching the contract: the enum-membership test fails.

## For deeper coverage

- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): the contract-ownership and schema-evolution patterns behind holding two stacks to one source document.
- J. Higginbotham, *Principles of Web API Design* (Addison-Wesley, 2021): governance practices for a contract that several teams or stacks consume.
- *Cloud Native Design Patterns*, "API Registry" chapter: one authoritative, versioned home for a contract, with compatibility rules gating breaking changes in CI.
- *Cloud Native Design Patterns*, "Protocols in Depth" chapter: the wire-format reasoning behind asserting field agreement, not byte-identical output, across two serializers.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `components.schemas`, `$ref` and operation shapes both generation paths read.
- [JSON Schema](https://json-schema.org/): the Draft 2020-12 vocabulary that `extract-message-schema.py` emits and both conformance tests validate against.
