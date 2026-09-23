# NES benchmark: Nova the Squirrel, level 1-1

`python bench/nes/run.py --rom nova.nes --decisions 100 --repeats 3`, run on 2026-09-24 with `jev-1.13.0`.

Both arms start from the same save state and use the same question pack (`next_action` Choice plus `danger` Noul), the same action loop, and the same last-action feedback. Only the state differs:

- **raw:** the player's position and flags, all 16 object slots, and the 13 level columns ahead, as raw numbers (pixel positions, type IDs, block IDs). About 30 facts.
- **jevbrief:** the adapter's facts in words, after its rules. Usually 2 to 4 facts.

| Arm | Furthest x (median, blocks) | Hits taken (total) | Deaths | Completed | Jev calls per run (median) | Median input tokens | Median latency (ms) | Median confidence |
|---|---|---|---|---|---|---|---|---|
| raw | 8.6 | 0 | 0 | 0/3 | 7 | 2,829 | 3,952 | 0.69 |
| jevbrief | **56.4** | 6 | 0 | 0/3 | 15 | **713** (−75%) | 4,299 | 0.82 |

| Run | Arm | Furthest x | Hits | Deaths | Jev calls | Errors |
|---|---|---|---|---|---|---|
| 1 | raw | 8.6 | 0 | 0 | 7 | 0 |
| 1 | jevbrief | 56.4 | 2 | 0 | 15 | 0 |
| 2 | raw | 8.6 | 0 | 0 | 7 | 0 |
| 2 | jevbrief | 56.4 | 2 | 0 | 15 | 0 |
| 3 | raw | 8.6 | 0 | 0 | 7 | 0 |
| 3 | jevbrief | 55.9 | 2 | 0 | 26 | 1 |

## What happened

- **raw** never passed the first obstacle, a sand block two blocks high at x ≈ 9. From block IDs and pixel positions, Jev did not pick a jump, and the unchanged state reused the same answer for the rest of the run. It took no hits because it never reached an enemy.
- **jevbrief** cleared the sand block, low walls (with `short_hop`), and the first Owls, reaching x ≈ 56 of the level map's 256 columns. Its hits are from flying Owls and fire enemies near x ≈ 45 to 55. Every run then stopped at a very tall wall where the path continues below a thin ledge, which needs `drop_down` at the right spot.
- Neither arm finished the level. **Jev is not a game-playing model**, and 100 decisions is a short run.

## Caveats

- **One level, three runs, one start state.** The emulator is deterministic, so runs differ only through Jev's answers; runs 1 and 2 were identical.
- **Latency is API noise here, not an effect.** Single calls ranged from about 0.3 s to 5 s in both arms (raw run 3 had a median of 413 ms). The emulator is paused during calls, so latency does not affect play.
- **Tuned while building.** The action set (`drop_down` was added after seeing the tall wall), option descriptions, last-action feedback, and the low-confidence policy were changed after watching early runs. The raw arm got the same feedback in raw form.
- **"Completed"** means reaching the end of the level map (256 columns). The level's real exit may be earlier, so this column is conservative.
- **Fewer calls is partly a jevbrief feature:** unchanged facts reuse the last answer. In the raw arm, reuse happened because Jev repeated a move that did nothing.
