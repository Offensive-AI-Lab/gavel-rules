# GAVEL Rules Library: Format Specification

This document defines the library's on-disk layout and file schemas. Use it to author a rule or CE by hand, check what a pull request must contain, or build tooling that consumes the library. For a guided walkthrough of a real rule, start with [GUIDE.md](GUIDE.md).

The repository files are the canonical interface. Every artifact can be read on GitHub and reviewed in a pull request without special tooling. Gavel Studio and `viewer.html` provide more convenient interfaces but are not required.

Versioned files carry a `schema_version`. The current version is `1` for every versioned file type: rule and CE YAML files, the manifest, rulesets, and datasets. `index.json` has its own generated schema, also currently version `1`; `categories.yaml` is not versioned. Versions change independently by file type.

## Directory tree

```
gavel-rules/
├── README.md
├── GUIDE.md                         # top-down walkthrough of a real rule
├── FORMAT.md                        # this file
├── gavel.yaml                       # repo manifest — declares the namespace
├── categories.yaml                  # the shared category taxonomy
├── index.json                       # GENERATED catalog — do not edit by hand
├── tools/                           # validator + index builder (uv scripts)
├── .github/workflows/               # CI: validate PRs, rebuild index on merge
│
├── rulesets/
│   └── paper_rules.yaml             # a named bundle of rules, by rule name
│
├── rules/                           # one directory per rule, named after it
│   └── romance_baiting/
│       ├── rule.yaml                # definition, firing logic, metadata
│       └── tests/
│           ├── positive.json        # conversations that MUST fire the rule
│           ├── negative.json        # conversations that must NOT fire
│           └── positive_calibration.json
│
└── ces/                             # one directory per Cognitive Element
    └── ethnoracial/
        ├── ce.yaml                  # definition, seed examples, metadata
        ├── calibration.json         # multi-turn threshold-calibration set
        └── excitation.json          # single-exchange probe-training set
```

## Naming and identity

* **The name matches the path.** A rule or CE lives in a directory with the same name: `rules/romance_baiting/`, `ces/ethnoracial/`. A ruleset's name matches its filename. Names must match `[A-Za-z0-9_]+` and be unique within their artifact type. Prefer specific, self-explanatory `lowercase_with_underscores` names.
* **`public_id` is permanent.** Each artifact carries an opaque identifier with a type prefix: `rule_<32 lowercase hex characters>`, `ce_<32 lowercase hex characters>`, or `ruleset_<32 lowercase hex characters>`. Mint it once and never reuse or change it, including when renaming the artifact. For example:

  ```sh
  uv run python -c "import uuid; print('ce_' + uuid.uuid4().hex)"
  ```

  Replace `ce_` with `rule_` or `ruleset_` for the other artifact types.
* **Cross-references use names, not IDs.** Rule groups list CE names, and rulesets list rule names. References may include a namespace; see [Namespaces and references](#namespaces-and-references). `index.json` provides name-to-ID mappings and derives each rule's CE dependency list from `groups`.

## Discovery metadata

The following fields make artifacts easier to find in the viewer, search, and Studio:

* **`title`** (CEs, rules, and rulesets; required): a one-line display name. Interfaces show "Go Somewhere" and "Romance Baiting" instead of `physical_movement_solicitation` and `romance_baiting`. It does not need to be unique.
* **`role`** (CEs only, required): which functional part a CE plays inside a detection. Exactly one value from a closed enum, versioned with the schema and extended only by spec change:

  | Role                | What the CE detects                              | Examples                                             |
  | ------------------- | ------------------------------------------------ | ---------------------------------------------------- |
  | `directive_to_user` | The assistant directing the user to act          | `physical_movement_solicitation`, `click_or_enter`   |
  | `llm_task`          | The task the model is performing                 | `content_creation`, `sql_query_crafting`             |
  | `llm_behavior`      | How the model is behaving                        | `being_sycophantic`, `trust_seeding`                 |
  | `topic`             | The subject under discussion                     | `tax`, `electoral_politics`                          |

  Roles help authors find CEs that serve complementary functions in a rule.
* **`categories`** (rules and rulesets only): policy domains defined in `categories.yaml`. CEs use `role` instead because they are reusable building blocks rather than policy statements.
* **`tags`** (CEs and rules, optional): finer-grained labels or external-framework mappings. Each tag must be lowercase and match `[a-z0-9_]+(\.[a-z0-9_]+)*`, for example `scam.romance` or `owasp.llm01`.

## File schemas

### `rules/<name>/rule.yaml`

```yaml
name: romance_baiting
title: Romance Baiting
public_id: rule_0907b0555fcd4754ad98fa865add8e03
schema_version: 1
categories:                    # taxonomy labels from categories.yaml (1..n)
  - Safety & Harm Prevention
definition: >
  Detects attempts to build emotional trust or intimacy in order to
  persuade someone to make a purchase, share personal information, ...
groups:                        # named CE groups — the building blocks
  emotional_hook: [emotionally_engaging]
  solicited_action: [buy_or_purchase, click_or_enter, send_or_transfer]
  rapport_tactic: [trust_seeding, role_playing]
condition: all of emotional_hook and 1 of solicited_action and 1 of rapport_tactic
provenance:
  created_by: your-github-handle
  published_at: "2026-06-11T09:59:26Z"
```

`groups` + `condition` **are** the rule: `groups` names the CE building blocks, `condition` is a boolean expression over those group names. The condition is the stored logic; tooling derives an expanded readable rendering into `index.json` for display.

#### `groups`

A mapping from group name to a non-empty list of CE names. Group names follow the same convention as artifact names (`[a-z][a-z0-9_]*`) and must be *descriptive*: name the role the group plays in the detection (`aggression`, `rapport_tactic`), not its position (`g1`, `group2`; CI lints against these). Names must not be one of the condition keywords (`all`, `of`, `and`, `or`, `not`). A CE may appear in more than one group. Conditions reference **group names only**, never bare CEs; a single-CE group is the way to reference one CE.

#### `condition` grammar

```
condition   ::= disjunction
disjunction ::= conjunction ( "or" conjunction )*
conjunction ::= atom ( "and" atom )*
atom        ::= selector | "(" condition ")"
selector    ::= ( "all" | INTEGER ) "of" GROUP_NAME
```

All keywords are lowercase. `and` takes precedence over `or`; parentheses override precedence. `k of g` is true when at least *k* distinct CEs in group *g* are detected in the conversation. `all of g` requires every CE in the group. *k* must satisfy `1 ≤ k ≤ |g|`. When *k* equals the size of the group, use `all of g`. Every selector must name a group explicitly.

**Negation is not supported.** `not` is a reserved keyword, and the validator rejects conditions that use it. Negation will remain unavailable until its calibration semantics are defined in a future schema version.

#### Validation (CI-enforced)

* every group referenced by `condition` is defined in `groups`;
* every defined group is referenced by `condition` (no dead groups);
* selector bounds and the `all of` lint above;
* group-name grammar, keyword collisions, and the descriptive-name lint;
* every CE named in `groups` exists in `ces/` (or arrives in the same PR).

#### Derived rendering in `index.json`

The index stores `groups` and `condition` verbatim and adds a readable predicate with groups expanded: `1 of g` becomes `(a OR b)`, `all of g` becomes `(a AND b)`, and `k of g` becomes `at least k of (a, b, c)`. The rule's CE dependency list is the union of its group members.

`provenance` records authorship: `created_by` is your GitHub handle, `published_at` an ISO-8601 timestamp. An optional `publisher: {username, hf_handle}` entry may appear when an organization publishes on behalf of an author. For artifacts **added** in a pull request, CI verifies that `created_by` matches the GitHub login of the PR author; later edits by others leave `created_by` untouched, because it records the creator.

### `rules/<name>/tests/{positive,negative,positive_calibration}.json`

```json
{
  "schema_version": 1,
  "rule": "romance_baiting",
  "rule_public_id": "rule_0907b055...",
  "type": "positive",
  "config": {"scenario_instructions": "..."},
  "conversation_count": 12,
  "conversations": [[{"role": "user", "content": "..."}, ...], ...]
}
```

`positive` conversations must trigger the rule; `negative` conversations must not. `positive_calibration` is a held-out positive set used for threshold tuning. Repository CI validates the dataset structure. Gavel Studio performs detector-side evaluation after training the required probes. Conversations are lists of `{role, content}` messages whose role is `user`, `assistant`, or `system`. `config.scenario_instructions` records the scenario used to author or generate the set and is the only allowed `config` key.

**Latent CEs and false positives.** A rule firing on a negative sample is not automatically a detector bug: the sample may contain *latent* CEs, content that genuinely satisfies the rule's condition even though the author didn't intend it. When a negative fires, first check whether the sample actually contains the rule's CEs; only then suspect the probes. Authors of negative sets should screen for this.

### `ces/<name>/ce.yaml`

```yaml
name: ethnoracial
title: Ethno-racial Reference
public_id: ce_0b4ff21ab8d24afca18244d737e54bc1
schema_version: 1
role: topic                    # closed enum — see Discovery metadata
definition: >
  Ethno-racial Reference: mentions race, ethnicity, nationality, or
  cultural background.
examples:                      # seed examples: should the CE fire?
  - {input: "This policy disproportionately affects Black communities.", output: "YES"}
  - {input: "This policy affects several communities.", output: "NO"}
provenance:
  created_by: your-github-handle
  published_at: "2026-05-07T09:27:59Z"
```

The `definition` is the contract: it is what the probe is trained to detect and what reviewers evaluate your datasets against. Write it precisely ("mentions race, ethnicity, nationality, or cultural background"), not vaguely. Include NO examples at the boundary where the concept is commonly over-triggered. `examples` are a handful of seed inputs with the expected YES/NO answer; they document intent (the real training data is the excitation set).

### `ces/<name>/{calibration,excitation}.json`

```json
{
  "schema_version": 1,
  "ce": "ethnoracial",
  "ce_public_id": "ce_0b4ff21...",
  "type": "calibration",
  "sample_count": 15,
  "samples": [[{"role": "assistant", "content": "..."}, ...], ...]
}
```

* **`excitation.json`**: single-exchange samples used to train the probe. Each sample contains a `system` prompt, one `user` message, and one `assistant` response. Hundreds of relevant, varied samples are typical.
* **`calibration.json`**: multi-turn conversations used to set and validate the probe's detection threshold in realistic dialogue.

Gavel Studio can generate candidate samples for both datasets from the CE definition. Review every candidate before including it in a PR. Tooling validates the JSON structure, but authors remain responsible for data quality.

### `rulesets/<name>.yaml`

```yaml
name: paper_rules
title: Paper Rules
public_id: ruleset_b34e5bd076d34ccfbf840f279e51a8cd
schema_version: 1
description: "The rules from the GAVEL paper — the library's founding set."
rules:                         # member rules BY NAME — readable, validated
  - romance_baiting
  - scamazon
  # Additional rules omitted from this example.
provenance:
  created_by: your-github-handle
  published_at: "2026-06-23T14:39:31Z"
```

A ruleset is a curated bundle that users can adopt as a unit. Its `description` states what belongs in the bundle and why, so adopters know what they are enabling. `index.json` derives the ruleset's categories from its member rules.

### `categories.yaml`

The shared taxonomy is a list of `{name, description}` entries. Rules may only use category names defined here; CI enforces this. Ruleset categories are derived from their member rules, and CEs use `role` instead of categories. Propose new categories in a separate PR because they affect the whole library. There is no catch-all entry: a rule that fits no existing category needs a new category or a tag, not "Other".

### `index.json` (generated)

CI rebuilds `index.json` after every merge to `main` (`.github/workflows/index.yml`). It catalogs each CE, rule, and ruleset, including discovery metadata, file paths, firing logic, dataset counts, content hashes, and derived relationships.

Consumers such as the viewer and Gavel Studio can read this single file instead of walking the repository. Never edit it by hand. To rebuild or verify it locally:

```sh
uv run tools/build_index.py
uv run tools/build_index.py --check
uv run tools/validate.py
```

## Contribution checklist

A PR may add CEs, rules, or both. CE-only PRs are welcome: a CE does not need a rule that uses it, and unused CEs are building blocks for future rules. The reverse is not true: a rule's referenced CEs must all exist.

A PR adding a **new CE** contains:

- [ ] `ces/<name>/ce.yaml`: definition, seed examples, `title` + `role`, freshly minted `public_id`, your handle in `provenance.created_by`
- [ ] `ces/<name>/excitation.json`
- [ ] `ces/<name>/calibration.json`

A PR adding a **new rule** contains:

- [ ] `rules/<name>/rule.yaml`: every referenced CE exists in `ces/` or is added in this PR
- [ ] `rules/<name>/tests/positive.json`
- [ ] `rules/<name>/tests/negative.json`
- [ ] `rules/<name>/tests/positive_calibration.json`

Do **not** edit `index.json`; CI regenerates it on merge.

## Namespaces and references

The library format is **federated**: each publisher owns a namespace and may publish CEs, rules, and rulesets within it. Organizations can define their own CEs; `gavel/` is the recommended shared vocabulary, not a requirement.

### The repo manifest

Each repository declares its default namespace in `gavel.yaml` at the root:

```yaml
# gavel.yaml
schema_version: 1
namespace: gavel                # this repo publishes into gavel/*
```

The namespace must match the GitHub organization or user that hosts the repository. This makes namespace ownership verifiable during ingestion. Files inherit the manifest namespace unless they provide an explicit `namespace` override. CI rejects a repository that publishes under a namespace it does not own.

Two namespaces are **reserved**:

* `local`: private to a deployment and never publishable. Use it for in-house artifacts that must not collide with published names.
* `gavel`: the reference vocabulary published by this repository.

### Reference syntax

The canonical fully-qualified form, used in URLs, error messages, aggregated indexes, and anywhere the artifact kind is ambiguous, is:

```
<namespace>/<kind>/<name>      # gavel/ce/trust_seeding, gavel/rule/romance_baiting
```

In files, the manifest supplies the default namespace and the referencing field usually supplies the artifact kind. References can therefore use any of these forms:

| Form                  | Example                    | Meaning                                      |
| --------------------- | -------------------------- | -------------------------------------------- |
| Bare                  | `trust_seeding`            | This repository's namespace; kind from field |
| Namespace-qualified   | `gavel/trust_seeding`      | Named namespace; kind from field             |
| Fully qualified       | `gavel/ce/trust_seeding`   | Namespace, kind, and artifact name           |

A rule may freely mix its own CEs with other namespaces' CEs in `groups`; a ruleset may list rules from any namespace.

### Resolution rules

1. Uniqueness is per `(namespace, kind)`: `gavel/ce/threat` and `gavel/rule/threat` may coexist; two CEs named `threat` in one namespace may not.
2. A file's namespace = its own `namespace:` field if present, else the repo manifest's.
3. Bare and namespace-qualified references get their kind from the referencing field (`groups:` → CE, `rules:` → rule). The fully-qualified form is required wherever the field does not determine the kind.
4. Indexes never contain shorthand ambiguity: a single-repo `index.json` declares its `namespace` once at the top and lists bare names within it; any aggregated multi-namespace index stores only fully-qualified names.

### Dependency resolution

An artifact that references another namespace is usable only after that namespace has been ingested and its probes have been trained. Tooling must report missing dependencies during ingestion and stop; it must not defer or silently ignore them at detection time. The ingestion report must list every external namespace and artifact the library depends on.

## Sync signatures

`index.json` carries a `content_hash` for each artifact and a repository-wide `global_signature`. Consumers and mirrors can compare these values to detect changes without walking the full tree.

Both values are reproducible from file contents. An artifact hash covers the `(path, sha256)` pairs in its directory; the global signature covers every artifact hash plus the shared files. The same tree therefore produces the same signature. Run `uv run tools/build_index.py --check` to verify it.
