# Launch Content

Full drafts for every channel in `docs/OPEN_SOURCE_LAUNCH_STRATEGY.md`'s
plan. Titles here already carry that document's local-first/open-source-
in-progress correction — none of these overclaim. **Not posted anywhere
yet** — the repo is now public, so the repo and Discussions links below
are filled in with the real, live URLs
(`https://github.com/mne03005-png/OpenVideoStudio` and
`.../discussions`). `{DEMO_URL}` remains a placeholder — there's no
separate hosted demo site; the demo is the GIF/video in `README.md` and
`examples/hero_demo/`.

Recommended posting order (detail in `docs/LAUNCH_72H_PLAN.md`):
**GitHub (anchor, hour 0) → Hacker News + X (day 1) → Reddit (24–48h
after HN, once there's visible traction to point to) → YouTube (week 1).**

---

## 1. GitHub (the repository itself)

Not a "post" — the README *is* the pitch. See `README.md` and the release
notes drafted in `docs/GITHUB_LAUNCH_SETUP.md` Section 7. No separate
content needed here beyond what those two already carry.

---

## 2. Hacker News

**Title:** I built an open-source AI video studio on a 6GB RTX 3060
laptop — now I'm opening it to everyone

**Post body** (Show HN posts are typically just a link + the poster
commenting in the thread, but here's the opening comment to post
immediately after submitting, which is standard HN practice):

> Hi HN — I built this on a laptop with an RTX 3060 6GB GPU, not a
> rented A100. Paying per-generation credits just to experiment wasn't
> realistic for me, and the hardware itself isn't especially powerful
> either — so instead of buying more compute, I built the workflow to
> actually run end-to-end on what I already had.
>
> OpenVideoStudio is a pipeline that turns one text prompt into a fully
> edited, narrated, subtitled video: script → storyboard →
> character/environment identity → keyframes → video clips → narration →
> subtitles → automated edit.
>
> It runs on local models (Ollama + ComfyUI/SDXL/LTX-Video) on that same
> 6GB laptop — see `docs/HARDWARE.md` in the repo for exactly what's
> tested vs. expected vs. unknown, since I'd rather under-claim than have
> someone's install fail on a claim I didn't actually verify. One thing
> I want to be upfront about: default narration uses Microsoft's Edge
> TTS, which is a cloud call — everything else in the pipeline is local,
> and that's the one exception, disclosed in the README, not buried.
> That constraint is also part of why it's "local-first," not "fully
> local" — I'd rather say that plainly than let "local" imply more than
> what's true.
>
> The provider layer (LLM/image/video/TTS) is a set of swappable
> interfaces — adding a new one is one file plus a two-line registration,
> not a fork. I'm opening it up specifically because there's real,
> scoped work I didn't build myself on purpose — Linux/macOS support, an
> OpenAI-compatible provider, character-consistency research, a timeline
> editor — see `docs/COMMUNITY_TRACKS.md` if any of that's your kind of
> problem. It's still genuinely unfinished in real places — character
> identity drifts across scenes more than I'd like — I'd rather open
> that up now than keep building it alone behind a closed door.
>
> Repo: https://github.com/mne03005-png/OpenVideoStudio
>
> Happy to answer anything about the architecture, the GPU-sequencing
> approach for fitting this on 6GB, or what's still rough.

**Short version** (if a character-limited summary is needed elsewhere):
"An open pipeline that turns a prompt into a full edited video —
local-first, script/image/video generation run on a 6GB GPU, one cloud
call (default TTS) disclosed in the repo — looking for contributors on
the parts I deliberately left unbuilt."

**CTA:** implicit — HN penalizes hard asks. The repo link and an active,
responsive comment thread *are* the CTA.

**Timing:** weekday, US morning (poster needs to be present and
responsive for several hours after posting).

---

## 3. Reddit

Three separate posts, not one crossposted — each written for that
subreddit's actual interests.

### r/StableDiffusion

**Title:** I built a full prompt-to-video pipeline on top of SDXL
Lightning + LTX-Video — script, storyboard, identity, keyframes, clips,
narration, all automated

**Opening paragraph:**

> Posting here because the image/video generation side is where most of
> the interesting technical decisions are. OpenVideoStudio chains SDXL
> Lightning (keyframes) and LTX-Video (image-to-video clips) behind an
> LLM-driven script/storyboard stage, with a canonical character/
> environment identity generated once and reused verbatim across every
> scene's prompt — instead of re-describing the character each time and
> hoping the LLM stays consistent, which is what drifted in an earlier
> version. Runs on a 6GB card by never keeping two heavy models resident
> at once (Ollama unloads before SDXL loads, which frees before LTX
> loads).

**Short version:** "Full prompt-to-video pipeline built on SDXL Lightning
+ LTX-Video, with a canonical identity system instead of re-describing
the character every scene. Open source, looking for contributors."

**CTA:** "Repo + install guide: https://github.com/mne03005-png/OpenVideoStudio — genuinely interested in
feedback on the identity-consistency approach specifically, that's the
part I'm least sure is the right long-term design."

### r/LocalLLaMA

**Title:** Built a local-first AI video pipeline (Ollama + ComfyUI) —
the LLM does script/storyboard/identity generation, everything chains
off that

**Opening paragraph:**

> Sharing here because the LLM side (Ollama, qwen3:8b by default but
> config-driven, not hardcoded) is doing more than people might expect
> in a "video generation" tool — it writes the script, breaks it into a
> shot-by-shot storyboard, and generates a structured character/
> environment identity in its own focused call before touching any image
> model. Provider selection is genuinely config-driven (verified by
> tests, not just claimed) — swapping the LLM provider doesn't touch
> pipeline code. (Built and tested on a 6GB RTX 3060 laptop, for the same
> reason a lot of this community cares about local models in the first
> place: paying per-generation credits just to experiment wasn't
> realistic for me, so the constraint became the design brief.)

**Short version:** "Local-first AI video pipeline — Ollama does script/
storyboard/identity generation, ComfyUI does the visuals. Open source,
provider-agnostic architecture."

**CTA:** "https://github.com/mne03005-png/OpenVideoStudio — an OpenAI-compatible provider adapter is on the
help-wanted list if anyone wants the highest-leverage contribution
available."

### r/opensource

**Title:** Launched OpenVideoStudio (Apache-2.0): an AI video pipeline
built with real community contribution tracks, not just a code dump

**Opening paragraph:**

> Wanted to share this here specifically because of how the contribution
> model is structured, not just the tool itself. The core pipeline is
> maintainer-led and tested; everything past it — AI art tooling,
> platform support, a timeline editor, character-consistency research —
> is scoped into eight tracks with explicit boundaries, deliberately left
> unbuilt so there's real work available, not busywork. Governance is a
> five-rung earned-trust model (Contributor → Trusted Contributor →
> Reviewer → Maintainer → Core Maintainer); sponsorship, when it's
> eventually activated, explicitly can't buy any of those rungs.
>
> I built the core of this alone, on a 6GB laptop GPU, without an AI
> budget beyond what that laptop can do — paying for generation credits
> just to experiment wasn't realistic for me. That's part of why the
> contribution model matters as much to me as the code: I don't want
> this to stay one person's project, and I'd like the Contributors page
> to eventually have more than one name on it.

**Short version:** "New Apache-2.0 AI video project with real, scoped
community contribution tracks and an earned-trust governance model —
not just code thrown over the wall."

**CTA:** "https://github.com/mne03005-png/OpenVideoStudio — `docs/COMMUNITY_TRACKS.md` and 43 seeded issues
if you want to see exactly what's open before you look at any code."

---

## 4. X (Twitter)

**Thread (5 posts):**

1. I built OpenVideoStudio on a laptop with an RTX 3060 6GB GPU — not a
   rented A100, and not an unlimited generation-credit budget either.
   One prompt → script → storyboard → keyframes → clips → narration →
   subtitles → final video. Open-sourcing it today.
   🧵
2. [demo clip embedded here]
3. The pipeline generates a canonical character + environment identity
   *once*, then reuses the exact same text on every scene's prompt —
   instead of re-describing the character every time and hoping it stays
   consistent. That was the fix for the biggest continuity problem in
   earlier versions.
4. Provider layer is genuinely swappable — LLM, image, video, TTS are all
   interfaces, config-driven selection, not hardcoded. One honest
   exception: default narration uses Edge TTS (cloud), disclosed clearly,
   not buried.
5. It's Apache-2.0, and I deliberately didn't build everything —
   character-consistency research, Linux/macOS support, an AI art
   studio layer, a timeline editor are all open, scoped tracks. Repo +
   43 seeded issues: https://github.com/mne03005-png/OpenVideoStudio

**Short version (single post, if a thread isn't the right format):** "I
built a local-first AI video studio on a 6GB RTX 3060 laptop — paying
per-generation credits to experiment wasn't realistic for me, so I built
the workflow instead. Prompt → full edited video, open source. One
disclosed exception: default narration is a cloud call (Edge TTS),
everything else stays on-device. Looking for contributors on the parts
I left unbuilt on purpose. https://github.com/mne03005-png/OpenVideoStudio"

**CTA:** repo link on the last post, pinned reply with the Discussions
link once live.

**Timing:** day 1, same day as HN.

---

## 5. YouTube

**Full shot-by-shot recording script:** [`docs/YOUTUBE_DEMO_SCRIPT.md`](YOUTUBE_DEMO_SCRIPT.md)
— what's below is the upload metadata (title/description/CTA); that file
is what you actually read from while recording.

**Video title:** "I Built an Open-Source AI Video Studio on a 6GB RTX
3060 Laptop — Now I'm Opening It to Everyone"

**Description (opening paragraph):**

> OpenVideoStudio turns a single prompt into a complete video — script,
> storyboard, character/environment identity, AI-generated keyframes and
> clips, narration, subtitles, all automated. This video walks through a
> real generation run start to finish, on the same 6GB laptop GPU the
> project is built and tested on. Script, storyboard, identity, keyframes,
> and clips all run on that local GPU; the one disclosed exception is
> default narration, which uses a cloud TTS call (Edge TTS) — covered at
> [timestamp] below. I built this alone, without an AI budget beyond what
> that laptop can do — paying per-generation credits just to experiment
> wasn't realistic for me, so I built the workflow instead of buying more
> compute. It's open source (Apache-2.0), still genuinely unfinished in
> real places (character consistency, the editor, Linux/macOS support),
> and actively looking for contributors — timestamps and links below.

**Short version (for the video's own hook, first 10 seconds):** "This
entire video — script to final cut — was generated by a prompt, on a
laptop GPU, with software I'm open-sourcing today."

**CTA:** "Full install guide and source: https://github.com/mne03005-png/OpenVideoStudio — Discussions:
https://github.com/mne03005-png/OpenVideoStudio/discussions"

**Timing:** week 1, not launch day — a real walkthrough needs more
production time than the README's short hero demo.

---

## Cross-channel consistency check

Every title and opening paragraph above was written or reviewed against
the same bar `README.md`'s headline was held to: no unqualified "runs
locally" / "fully local" claim stands without the Edge TTS
cloud-call caveat nearby (an earlier draft of this file missed this in
several short-form spots — the YouTube title, the HN and X short/single-
post versions — all fixed; "local-first" titles that don't claim totality were left as-is, since that
phrasing is already accurate without a caveat). No unqualified "open
source" ahead of the Apache-2.0 license actually being in place (it now
is — see `docs/LICENSE_STRATEGY.md`), and no hardware claim beyond what
`docs/HARDWARE.md` actually verifies. This check is a description of what
was done, not a standing guarantee — re-run your own scan for "local" /
"cloud" / "offline" across this file before actually
posting anything, since it's easy for a future edit to reintroduce the
same gap.

A founder-story pass was added after the above (6GB RTX 3060 laptop,
built without a large AI budget, opening it up rather than building it
alone) across every channel and `README.md`. It was held
to the same rules the rest of this file is: "local-first," not "fully
local"; the 6GB RTX 3060 claim used only because `docs/HARDWARE.md`
actually verifies it; no claim that character consistency is solved; no
claim the project is finished — unfinished areas (character consistency,
more providers, the editor, Linux/macOS) are named as open contribution
opportunities, not glossed over or presented as done. Sincere and
specific, not a fundraising pitch and not pity-seeking — no mention of
sponsorship or donations anywhere in the story itself.
