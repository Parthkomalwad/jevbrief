# jevbrief launch plan

The goal of launch week is for Jev developers to know jevbrief exists, try `jevbrief inspect` in under a minute, and star or open an issue on the repo.

## Assets (in the repo)

| Asset | Path | Use |
|---|---|---|
| Demo GIF (real Jev calls) | `docs/assets/demo.gif` | README hero, X post, Show HN |
| Animated pipeline | `docs/assets/pipeline.svg` | README "How it works", explaining the idea |
| Viewer screenshot | `docs/assets/viewer.png`, `viewer-dark.png` | X replies, docs |
| Social preview card | `docs/assets/social-preview.png` | Upload in GitHub Settings, then Social preview |
| Agent skill | `skills/jevbrief/SKILL.md` | "Use with Claude Code / Cursor" posts |
| Benchmark | `bench/results.md` | Proof, with honest caveats |

Regenerate the GIF after any viewer change: `python scripts/make_demo_gif.py` (needs `pip install pillow`).

## Before posting

- [ ] Publish v0.1.0 to PyPI and confirm `pip install jevbrief` works in a clean environment.
- [ ] Tag `v0.1.0` and create a GitHub release with the benchmark table and the GIF.
- [ ] Upload the social preview image in the repo settings.
- [ ] Record a 30 to 60 second screen video: `python examples/click_agent.py --headed`, then `jevbrief view`. X plays video better than GIFs.
- [ ] Pin the repo on your GitHub profile.

## Day 1: launch

**X post (attach the video):**

> jevbrief v0.1 is live: an open-source SDK that turns messy web pages into small, clean state for @typesafeai's Jev.
>
> Same Jev, same tasks: 57% fewer input tokens, same accuracy.
>
> Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.
>
> pip install jevbrief
> github.com/parthkomalwad/jevbrief

**Reply thread (one image each):**

1. The viewer screenshot: "Every dropped element gets a reason code, so a wrong click is debuggable."
2. The benchmark table: "Honest numbers: synthetic pages, Jev was already accurate, the win is cost and auditability."
3. The SKILL.md: "Using Claude Code or Cursor? Drop this skill in and your agent knows how to use it."
4. "`jevbrief inspect <url> --goal ...` needs no API key. Try it on your own site."

**Show HN:** "Show HN: jevbrief – see what your browser agent's model was told, and what it wasn't". Link the repo, and put the GIF and the three-line quick start in the first comment.

## Days 2 to 7

- Submit to the awesome-jev lists and shipwithjev.com.
- Reply to every comment and issue on launch day.
- Post one short tip a day, each with one image:
  - "Why didn't my agent click Checkout?" (a `low_score` or `budget` drop in the viewer)
  - "Sync or async Playwright, three lines each"
  - "Use jevbrief as a filter in front of any model: `brief.state()`"
  - A real site run on a popular page with `jevbrief inspect`
- Write one blog post (dev.to or Hashnode): "Your browser agent sends 5,400 tokens per click. It needs 2,300."

## What not to do

- Do not post estimated numbers. Use only `bench/results.md` or a new real run.
- Do not use TypeSafe's logo or imply the project is official. Keep "Community project, not affiliated with TypeSafe AI".
- Do not claim accuracy gains. The measured gain is tokens and auditability.
