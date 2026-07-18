<p align="center">
  <img src="assets/gavel-logo.png" alt="GAVEL Rules" width="460">
</p>

<p align="center"><strong>A community-maintained library of detection rules for LLM behavior,<br>built from signals in a model's internal activations.</strong></p>

<h3 align="center">📖 New to GAVEL? Start with the <a href="GUIDE.md">User Guide</a></h3>

## What GAVEL does

GAVEL detects what a language model is doing in a conversation—for example, building romantic trust to push a purchase, drafting a phishing message, or reinforcing delusional thinking.

Like Snort or YARA, GAVEL combines simple signals into higher-level detections. Instead of matching patterns in the model's output, a lightweight multi-label classifier (a *probe*) reads the model's internal activations and scores **Cognitive Elements (CEs)** such as `emotionally_engaging`, `payment_tools`, and `making_threat`. A **rule** combines those CE detections into a named behavior using CE groups and a boolean condition:

```yaml
# rules/romance_baiting/rule.yaml (excerpt)
groups:
  emotional_hook: [emotionally_engaging]
  solicited_action: [buy_or_purchase, click_or_enter, payment_tools]
  rapport_tactic: [trust_seeding, role_playing]
condition: all of emotional_hook and 1 of solicited_action and 1 of rapport_tactic
```

This repository contains the shared CE definitions, rules, and datasets used to train and validate detectors. All artifacts are reviewable YAML or JSON; the repository contains no binaries or model weights.

## Content advisory

Detecting harmful behavior requires examples of it. The rule and CE datasets contain realistic **synthetic** conversations depicting the behaviors this library detects: scams and manipulation, threats, hate speech (including racist and homophobic language), and delusional or conspiratorial dialogue. This material exists solely to train and validate detectors — it reflects no one's views, and none of it describes real people or events. Keep this in mind before browsing `rules/` and `ces/` or reviewing dataset PRs.

## What's in this repository

| Path                                  | Contents                                                                          |
| ------------------------------------- | --------------------------------------------------------------------------------- |
| [`rules/`](rules/)                   | Rule definitions and their positive, negative, and calibration test conversations |
| [`ces/`](ces/)                       | CE definitions and their probe-training and threshold-calibration data            |
| [`rulesets/`](rulesets/)             | Curated bundles of rules that can be adopted together                             |
| [`categories.yaml`](categories.yaml) | Shared policy-domain taxonomy for rules                                           |
| [`index.json`](index.json)           | Generated catalog of the library; CI rebuilds it after each merge                 |
| [`GUIDE.md`](GUIDE.md)               | **User guide** — how the library works, told through one real rule                |
| [`FORMAT.md`](FORMAT.md)             | Complete layout, schema, grammar, and naming specification                        |

## Quick start

**Browse the library.** Start with the [library viewer](https://offensive-ai-lab.com/gavel/viewer/), or inspect [`rules/`](rules/) and [`ces/`](ces/) directly on GitHub. To run the viewer locally, start a static web server from the repository root:

```sh
python3 -m http.server 8642
```

Then open [http://localhost:8642/viewer.html](http://localhost:8642/viewer.html).

**Use the rules.** Install [Gavel Studio](https://github.com/Offensive-AI-Lab/gavel-studio-v2.0) and add this repository as a library. Studio helps you train probes for your model on your own hardware, validate the rules, and monitor model or agent traffic.

**Contribute.** Read the [user guide](GUIDE.md), then use the [format specification](FORMAT.md) while preparing your files.

## Core concepts

* **Cognitive Element (CE):** one detectable concept. Its `ce.yaml` defines the concept and gives seed examples. Its **excitation** dataset trains a probe; its **calibration** dataset helps set and validate that probe's detection threshold.
* **Rule:** one behavior to detect. Its `rule.yaml` organizes CEs into named groups and applies a boolean condition to those groups. Its test datasets contain conversations that should and should not trigger the rule.
* **Ruleset:** a curated bundle of rules that can be adopted together. The [`paper_rules`](rulesets/paper_rules.yaml) ruleset contains the library's founding set, the rules from the GAVEL paper.

The full layout and file schemas are specified in [FORMAT.md](FORMAT.md).

## The ecosystem

| Component                         | Purpose                                                                                                         |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| **gavel-rules** (this repo) | Source of truth for rules, CEs, and their datasets. Changes are contributed by pull request.                    |
| **Gavel Studio**            | Local application for ingesting libraries, training probes, validating detections, and authoring rules and CEs. |
| **Probes**                  | Lightweight classifiers trained locally for the model you want to monitor.                                      |

## Contributing

Contributions are submitted by pull request. If you are new to authoring, start with the [user guide](GUIDE.md); use [FORMAT.md](FORMAT.md) for exact requirements.

* **New CE:** add `ces/<name>/ce.yaml`, `excitation.json`, and `calibration.json`. A CE may be contributed without a rule.
* **New rule:** add `rules/<name>/rule.yaml` and all three datasets under `tests/`. Every referenced CE must already exist or be included in the same PR.
* **Rule idea or false-positive report:** open an issue; you do not need to author the files yourself.

Before opening a PR, run:

```sh
uv run tools/validate.py
```

CI repeats these structural checks. Detector-side tests run in Gavel Studio because the trained probes are not stored in this repository. Gavel Studio can generate candidate datasets, but contributors are responsible for reviewing every sample included in a PR. Do not edit `index.json`; CI regenerates it after merge.

## License

The rule and CE definitions and all datasets are released under the MIT-style license in [LICENSE](LICENSE), the same license as [Gavel Studio](https://github.com/Offensive-AI-Lab/gavel-studio-v2.0). By contributing, you agree to release your contribution under that license.
