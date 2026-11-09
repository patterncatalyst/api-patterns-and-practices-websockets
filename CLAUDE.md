# API Patterns and Practices: WebSockets

Chaptered Jekyll site (`_docs/`, `_parts/`) teaching WebSocket API design on two stacks, Quarkus
(WebSockets Next) and Python (`websockets`), with one AsyncAPI 3 contract in `contracts/` and a
runnable example per part under `examples/`. Planning notes live in
`_plans/` and are not published.

## Writing rules

- **Write like the EIP-Camel book** (`~/Dev/enterprise-integration-patterns-with-camel`): get to
  the point, show the code, state the trade-off, stop. Geewax tone; run
  `lgtm-professional-voice` on every change.
- **Length:** about 2,000 words of prose a chapter is the target and 2,500 the most. There is no
  floor: a chapter that is complete in fewer words stays that way. Never pad.
  `scripts/wordcount.sh` reports; `GATE=1` fails a chapter over 2,500.
- **Spine:** Learning objectives, Why this matters, the topic H2s, When not to use it (where it
  applies), the AI callout, Build, run, observe, For deeper coverage. A chapter that teaches a
  named API pattern may use `## Pattern: <Name>` H2s, each with `### The problem`,
  `### The solution` (a bold one-sentence definition) and `### How Quarkus and Python model it`.
- **No test names, no code narration, no self-reference.** Prose never names a test or a
  `verify.sh` assertion and never walks a code block line by line. No "this chapter", "the
  example shows", "the suite". Exception: "By the end of this chapter you can:" before the
  objectives.
- **Build, run, observe:** the commands, what passes, then one bullet per experiment (what to
  change, what fails).
- **AI callout ("Explore with your agent"):** exactly one per technique chapter (01 to 24, and 27), a
  plain blockquote:

  ```
  > **🤖 Explore with your agent**
  >
  > "<runnable prompt naming the example's own endpoints, messages, close codes and files, and the chapter's decision rule>"
  >
  > Check: <the command to run or what to look for>
  ```

  No HTML wrapper, no nested quote, never a claim about what an assistant does.
- **At least one figure per chapter**, generated from a spec in `scripts/diagrams/` with
  `scripts/generate_diagram.py` (SVG + `.excalidraw`). Never hand-edit an SVG. Captions read
  `Figure N.x: <what it shows>`.
- **No em or en dashes** in reader-facing content: chapters, READMEs, `index.html`, `_parts/`,
  example pages, figure labels, deck text and notes.
- **Chapters stand alone:** no "Chapter 10", "ch04" or "as we saw earlier". Name the idea.
- No internal codes (rNN, DRQ-###, `_plans/` paths) in reader-facing files. Say "final project",
  never "capstone".
- Codetabs (`{% include codetabs.html %}`) and every kept listing stay byte-exact with the
  example source (there is no validator script; check them by hand).

## Gates before a commit

```bash
GATE=1 bash scripts/wordcount.sh
bash ~/.claude/skills/lgtm-professional-voice/scripts/scan.sh --tier ban .
python3 ~/Dev/lgtm-skills/skills/lgtm-host-scrub/scripts/host_ids.py check
```

Build the site in a `ruby` container (the host has no ruby-devel).

## Git

One `release/rNN` branch and PR per iteration, squash-merged on the owner's OK, then an `rNN.x`
tag and a notes-only release. Never commit to `main`. No home paths, account names or machine
details in any tracked file.
