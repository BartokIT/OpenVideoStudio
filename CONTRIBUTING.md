# Contributing to OpenVideoStudio

Thanks for considering it. This guide covers how to report issues, how to
find something to work on, how the review process works, and how you
earn more trust (and more repository access) over time.

## Welcome contributors

OpenVideoStudio welcomes contributions from AI researchers, developers,
video creators, workflow designers, documentation contributors, and
testers — you don't need to be all of those at once, and you don't need
to be an AI expert. A typo fix in `docs/INSTALL.md` is as genuinely
welcome as a new provider.

Contribution areas this project explicitly wants, not just tolerates:

- **AI model integration** — new LLM/image/video/TTS providers (see the
  Model Gateway and Provider Integrations tracks in
  [`docs/COMMUNITY_TRACKS.md`](docs/COMMUNITY_TRACKS.md))
- **Video generation workflows** — pipeline stages, checkpointing,
  resumability, the review-gate mechanics, shared prompt/storyboard
  workflows (see the [Workflow share](.github/ISSUE_TEMPLATE/workflow_share.md)
  template)
- **UI/UX improvements** — the editor (`studio/web`: vanilla JS modules,
  no build step), the storyboard review, the Remix timeline
- **Documentation** — install guides, architecture explanations, fixing
  something that confused you
- **Examples** — see [`docs/good-first-issues.md`](docs/good-first-issues.md)
  for realistic starter tasks
- **Testing** — new test coverage, hardware reports on GPUs/OSes not yet
  in [`docs/HARDWARE.md`](docs/HARDWARE.md), cross-platform validation
- **Translations** — see the Documentation & Localization track in
  [`docs/COMMUNITY_TRACKS.md`](docs/COMMUNITY_TRACKS.md)
- **Bug reports** — see "Reporting an issue" below

### The contribution workflow, in one picture

```
Discussion
    ↓
Issue
    ↓
Pull Request
    ↓
Code Review
    ↓
Merge
```

Not every contribution starts at the top — a clear bug report can go
straight to an Issue, and a trivial docs fix can go straight to a PR. But
**new contributors are encouraged to start with discussions or good
first issues before making large changes** — it's the easiest way to
confirm the direction is right before you invest real time. See "Good
first issues" and "Find something to work on" below, and "What needs
discussion first" for the cases where a Discussion isn't just encouraged
but expected first.

### Good first issues

New here? [`docs/good-first-issues.md`](docs/good-first-issues.md) has
realistic, beginner-friendly starter tasks — documentation, examples,
translations, small UI fixes — cross-referenced against the real, live
`good first issue`-labeled issues in this repo, not a hypothetical list.
You're welcome either way: pick a listed task, or open a Discussion with
your own idea.

## Reporting an issue

Before opening anything, check whether it's actually a bug/feature/model
request versus a usage question — usage and "how do I" questions belong
in [Discussions](../../discussions), not Issues (see
`.github/ISSUE_TEMPLATE/config.yml`).

For everything else, pick the template that fits:

- **Something's broken** → [Bug report](.github/ISSUE_TEMPLATE/bug_report.md) —
  include what happened, what you expected, exact repro steps, and your
  environment (OS, GPU/VRAM, Python version, commit hash).
- **An idea, or a community-track proposal** → [Feature request](.github/ISSUE_TEMPLATE/feature_request.md)
- **A new LLM/image/video/TTS provider** → [Model request](.github/ISSUE_TEMPLATE/model_request.md)
- **A prompt/storyboard combination worth sharing** → [Workflow share](.github/ISSUE_TEMPLATE/workflow_share.md)
- **A security vulnerability** → **not a public issue** — see
  [`SECURITY.md`](SECURITY.md)'s private reporting process.

A good issue is one a maintainer can act on without a round of
clarifying questions: concrete repro steps beat a general description,
and "here's what I expected instead" beats "this is wrong."

## Find something to work on

1. Check [`docs/ISSUES_SEED.md`](docs/ISSUES_SEED.md) / the repo's Issues
   tab for a `good first issue` if this is your first contribution here —
   each one has a full spec (problem, why it matters, relevant files,
   expected result, acceptance criteria, how to test).
2. Browse [`docs/COMMUNITY_TRACKS.md`](docs/COMMUNITY_TRACKS.md) if you
   want to work in a specific area (AI Art, Model Gateway, Character
   Consistency, Platform Support, Timeline/Editor, AI Video QC,
   Documentation/Localization) — it lists that track's vision, boundaries,
   and starter/help-wanted/research issues.
3. Have an idea that isn't in either? Open a
   [GitHub Discussion](../../discussions) under **Ideas** before writing
   code, especially if it touches a shared interface (see "What needs
   discussion first" below).

**Comment on the issue before starting significant work** — it's the
easiest way to avoid two people building the same thing.

## Difficulty levels

- **good first issue** — genuinely small and well-scoped, with every field
  in the issue spec filled in. If you find a `good first issue` that's
  actually vague or huge, say so — it was mislabeled.
- **help wanted** — meaningful, independently implementable work that
  doesn't require rewriting core architecture.
- **research** — open-ended; contributions can be papers, benchmarks,
  experiments, or prototypes, not only finished PRs.

## Development setup

See [`docs/INSTALL.md`](docs/INSTALL.md). To run the test suite (no live
services required — LLM/image/video providers are faked in tests):

```bash
cd studio
python -m pytest tests/ -q
```

## Making a change

1. **Fork the repository** (top-right on GitHub), then clone your fork
   locally.
2. **Branch from `main`.** Name it so a reviewer can tell what it's for
   at a glance — `fix/<short-description>`, `feature/<short-description>`,
   or `docs/<short-description>` (e.g. `fix/subtitle-font-linux`,
   `feature/openai-provider`). Not enforced by tooling, just a courtesy.
3. **Write tests for what you change** — this project's test suite exists
   specifically because past bugs (see commit history) were caught by
   exactly this discipline. A PR that changes pipeline behavior without a
   test covering it will be asked to add one before review.
4. **Sign off your commits** (`git commit -s`) — see "Developer
   Certificate of Origin" below.
5. **Open a PR** against `main`, using the template in
   `.github/PULL_REQUEST_TEMPLATE.md`.

### Code contributions

- Match the style already in the file you're editing rather than
  introducing a new convention.
- Prefer a focused PR over a sprawling one — a change that touches one
  pipeline stage is easier to review (and revert, if needed) than one
  that touches five.
- If your change affects a shared interface, see "What needs discussion
  first" below — raise it in a Discussion before writing the PR, not
  after.

### Documentation contributions

Docs fixes don't need the full dev environment set up — you can edit
Markdown directly on GitHub for small changes (typos, broken links,
clarifications) and open a PR the same way. For anything larger (a new
guide, a restructure), open a Discussion first so the shape is agreed
before you write it. Docs PRs go through the same review process as code
— see [`docs/COMMUNITY_TRACKS.md`](docs/COMMUNITY_TRACKS.md)'s
Documentation & Localization track for translation-specific guidance
(keeping factual claims, especially hardware/feature-status ones, in
sync with the English original is the main thing reviewers check).

## What needs discussion first

Changes to shared interfaces affect every downstream community track at
once, so they need a Discussion before a PR, not after:

- `studio/providers/base.py`'s provider interfaces
  (`LLMProvider`/`ImageProvider`/`VideoProvider`/`TTSProvider`)
- `CreativeRunState`'s stage model or the review-gate mechanics in
  `studio/creative/pipeline.py`
- Anything in `studio/core/` that Media Remix also depends on

Everything else — new providers, new community-track features, docs,
tests, bug fixes — can go straight to a PR.

## Developer Certificate of Origin (DCO)

Every commit must be signed off (`git commit -s`), certifying you wrote it
or otherwise have the right to submit it under the project's license, per
the standard [DCO](https://developercertificate.org/) text. This is
lighter-weight than a CLA — no separate agreement to sign, just a
sign-off line in your commit message.

## Review process

- `good first issue` PRs get reviewed fastest — a quick first-contribution
  experience matters more than review-queue ordering.
- Every PR gets a response (approval, requested changes, or "still
  reviewing, thanks for your patience") within a reasonable window; if
  it's been quiet for a while with no response, a bump comment is
  completely fine.
- Review feedback is about the code, not the contributor — see
  [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## Recognition

Every merged PR gets you added to [`CONTRIBUTORS.md`](CONTRIBUTORS.md) and
a specific thank-you, not just a silent merge. See
[`GOVERNANCE.md`](GOVERNANCE.md) for how sustained contribution turns into
Trusted Contributor / Reviewer / Maintainer status.
