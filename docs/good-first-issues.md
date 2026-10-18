# Good First Issues

Two lists here, kept deliberately separate so this page never implies
more exists than actually does:

1. **Already filed** — real, live issues on GitHub today, labeled
   `good first issue`, each with a full spec (problem, why it matters,
   relevant files, expected result, acceptance criteria, how to test).
   Pick one and comment before starting, per
   [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
2. **Not yet filed** — realistic task ideas that aren't issues yet. If
   one interests you, open a Discussion or file it yourself using the
   [Good first issue template](../.github/ISSUE_TEMPLATE/good_first_issue.md)
   — don't assume it's claimed just because it's listed here.

## Already filed (pick one)

| # | Title |
|---|---|
| [#2](https://github.com/mne03005-png/OpenVideoStudio/issues/2) | [Platform] Cross-platform subtitle font path fallback |
| [#3](https://github.com/mne03005-png/OpenVideoStudio/issues/3) | [Docs] Add Windows install screenshots to docs/INSTALL.md |
| [#4](https://github.com/mne03005-png/OpenVideoStudio/issues/4) | [Docs] Translate README to a new language |
| [#5](https://github.com/mne03005-png/OpenVideoStudio/issues/5) | [QC] Clear error message when Ollama is unreachable |
| [#6](https://github.com/mne03005-png/OpenVideoStudio/issues/6) | [Model Gateway] Provider health-check CLI command |
| [#7](https://github.com/mne03005-png/OpenVideoStudio/issues/7) | [QC] Subtitle timing QC — cue falls within scene's clip duration |
| [#8](https://github.com/mne03005-png/OpenVideoStudio/issues/8) | [Docs] Hardware report template + first entries |
| [#9](https://github.com/mne03005-png/OpenVideoStudio/issues/9) | [Art Studio] Define a starter style preset schema (no loader yet) |
| [#10](https://github.com/mne03005-png/OpenVideoStudio/issues/10) | [Testing] COMFYUI_ROOT path handling test |
| [#11](https://github.com/mne03005-png/OpenVideoStudio/issues/11) | [Docs] FAQ for common install errors |

Full list of all seeded issues (including `help wanted` and `research`
tier): [`ISSUES_SEED.md`](ISSUES_SEED.md).

## Not yet filed — candidate ideas

These map to realistic, low-friction contributions but don't exist as
issues yet. Worded to match what's actually true today — not every
plausible-sounding task is one this project can support as described:

1. **Add a new workflow example** under `examples/` — a real prompt +
   settings you ran, with honest results (see the
   [Workflow share](../.github/ISSUE_TEMPLATE/workflow_share.md)
   template).
2. **Improve the installation documentation** — `docs/INSTALL.md` is
   already thorough; the gap is usually a step that only becomes
   confusing in practice. Note it, or open a PR fixing it.
3. **Test GPU/hardware compatibility** — run the full pipeline on
   hardware not yet listed in `docs/HARDWARE.md` and file a
   [Hardware report](../.github/ISSUE_TEMPLATE/hardware_report.md).
   Real reports from real runs only — no speculative entries.
4. **Add a supported-model reference table** — a single doc page listing
   exactly which checkpoint filenames the code expects and where they
   come from (this partially exists in `docs/INSTALL.md`'s model table;
   a contribution here would mean expanding or cross-referencing it, not
   claiming new models are supported).
5. **Improve an error message** — pick one from `providers/` or
   `creative/` that's unclear when it fails, and make it name the actual
   problem (see issue #5 above for the Ollama-specific version already
   filed).
6. **Add a demo project** — a second `examples/` entry alongside
   `hero_demo/`, disclosed with the same honesty (see
   `examples/hero_demo/README.md` for the bar to match).
7. **Add a translation** — only English exists today. See the Documentation & Localization track in
   [`COMMUNITY_TRACKS.md`](COMMUNITY_TRACKS.md).
8. **Suggest a small UI improvement** — the editor in `studio/web`
   (vanilla JS, no build step); a labeling, layout, or clarity fix is a
   real, scoped contribution.
9. **Add documentation screenshots** — the install guide and README
   describe the editor in text; real screenshots (redact any local
   paths first) would help a lot.
10. **Try an alternative Ollama-compatible LLM model** — the LLM
    provider is genuinely config-driven (`config.toml`'s `ollama_model`)
    — pull a different model, run the pipeline, and report what changed
    in a Discussion. (This is different from swapping the image/video
    model, which today only has one shipped implementation each — SDXL
    Lightning and LTX-Video — adding a second is Track D / Model
    Gateway work, not a first task.)

Have an idea that isn't here? Open a
[Feature request](../.github/ISSUE_TEMPLATE/feature_request.md) or start
a [Discussion](../../discussions) under Ideas.
