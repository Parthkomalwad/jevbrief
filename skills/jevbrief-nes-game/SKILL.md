---
name: jevbrief-nes-game
description: Add a new NES game to jevbrief, so TypeSafe's Jev can play it from the game's memory. Covers the legal ROM check, finding and verifying the memory map, turning memory into facts in words, actions, rules, tests, a benchmark, and the live viewer. Use when someone asks to support another NES game, write an NES game mapping or adapter, or make Jev play an NES game.
---

# Add an NES game to jevbrief

The `nes` adapter (`jevbrief/adapters/nes/`) plays Nova the Squirrel. A new game follows the same shape: **memory → facts in words → rules → one action question → hold the action → trace**. Read these first, and copy their patterns:

- `jevbrief/adapters/nes/__init__.py`: memory map constants, `extract()`, rules, pack, `raw()`
- `jevbrief/adapters/nes/game.py`: emulator wrapper, `hold()`, `play()`
- `bench/nes/verify_ram.py`, `tests/test_nes.py`, `bench/nes/run.py`, `docs/adapters/nes.md`
- `ADAPTERS.md` (the general adapter contract) and TypeSafe's [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)

Work in this order and show the user the result of each step before the next.

## 0. The ROM must be legal

- Never download, link, or ship a commercial ROM (Nintendo, Capcom, and so on). Downloading them is copyright infringement in most countries, even for owners.
- Allowed: homebrew released for free by its author (check the license and quote it to the user), or a dump the user made from a cartridge they own, used only on their machine.
- The user passes the ROM path. It never goes into the repo, tests, traces, or the package. Record the ROM's SHA-1 and warn when a different file is used, as `game.py` does.

## 1. Boot the game

`pip install "jevbrief[nes]"` (cynes emulator). cynes buttons are bits: A 128, B 64, SELECT 32, START 16, UP 8, DOWN 4, LEFT 2, RIGHT 1. Write the input script that gets from power-on to the first playable moment (title, menus). Save PNGs of frames and look at them to confirm each step.

```bash
python skills/jevbrief-nes-game/ram_search.py --rom game.nes --script "none*120,START*10,none*180" --save boot.state --png boot.png
```

## 2. Find the memory map

Prefer, in this order:

1. **The game's source code.** Build it with its assembler and a label file (ca65: `ld65 ... -Ln labels.txt`) to get exact addresses. Variables placed by the linker have no fixed address in the source.
2. **A community RAM map or disassembly** (for example Data Crystal). Cross-check two sources; they disagree more often than you would expect.
3. **Memory search** with `ram_search.py`: play one controlled input from a saved state and compare.

```bash
python skills/jevbrief-nes-game/ram_search.py --rom game.nes --load boot.state --script "RIGHT*60"         # x: steadily up
python skills/jevbrief-nes-game/ram_search.py --rom game.nes --load boot.state --script "A*15,none*45"      # y: back and forth
python skills/jevbrief-nes-game/ram_search.py --rom game.nes --load boot.state --script "RIGHT*300" --watch 0x86,0x6d
```

Find at least: player x and y (and the screen scroll), on-ground or jumping, health or lives, the object slot table (type, x, y, active), level number, and, if the game keeps one in RAM, the level map plus which blocks are solid. Many games keep the level in cartridge RAM ($6000-$7FFF) and block flags in a table. Note the units: pixels, 16-pixel blocks, or block plus fraction.

## 3. Verify it against the running game

Write `bench/nes/verify_<game>.py` like `verify_ram.py`: scripted inputs, then assertions (x rises when walking right, y falls then rises in a jump, the first enemy appears with the expected type, health drops on a hit). Draw the computed boxes on a frame and look at it, to fix offsets (for example, x is the sprite's center, y its top). The same script records small RAM snapshots for tests with `save_snapshot`.

Also find what a death and the level's end look like in memory. Some games never show health 0; they respawn at once with full health.

## 4. Extract facts in words

Jev is weak at numbers, coordinates, counting, and hex. Compute everything in code and send words:

| Raw memory | Fact sent to Jev |
|---|---|
| enemy slot: type 6, x 212 (player 180) | `Goomba: ahead, close, same height` |
| level columns ahead with solid blocks | `Wall ahead, low (one block), touching`, `Pit ahead, wide, close` |
| health 1 of 4 | `health: one hit left` |
| last action did nothing | `last_action: drop_down, nothing changed` |

Reuse `distance()`, `height()`, `health()`, `png()`, `save_snapshot()`, and `load_snapshot()` from `jevbrief.adapters.nes`. Put raw values only in `meta` (with `meta["box"] = [x, y, w, h]` in screen pixels for the viewer), return the frame as a PNG image, and give facts stable IDs (slot number, level column). Always include `last_action` feedback: without it, an action that changes nothing leaves the state unchanged, and the same answer is reused forever.

## 5. Rules, actions, and the question

- Name the adapter `nes_<game>` and namespace every reason code `nes_<game>.<code>`, each with a plain description. Start from the nes rules: inactive slot, effect, offscreen, behind the player, far ahead; boost threats and obstacles in the path.
- Actions are a small fixed set: `name: (description, buttons, frames)`. Describe what each clears and when it works, literally ("Only works when `player.standing_on` is a thin ledge"). Watch real runs and add actions the level needs (Nova needed `drop_down`).
- Ask one `OptionChoice` plus a `danger` Noul in the same call. The emulator only steps inside `hold()`, so it is paused while Jev answers.

## 6. Test, benchmark, document

- `tests/test_<game>.py`: `check_adapter` on a recorded snapshot, one test per reason code (patch the snapshot bytes to create each case), extraction from snapshots, and a test that the state has no digits. Add a README next to recorded snapshots with the game's license, because they contain its level data.
- Benchmark with `bench/nes/run.py` as the model: raw memory against facts, the same start state and loop, fixed decisions, 3 runs. Report furthest progress, hits, deaths, completion, tokens, and latency, with caveats (one level, tuned while building, API latency noise). Never claim a gain you did not measure.
- Docs in `docs/adapters/nes_<game>.md`: where to get the legal ROM, what Jev sees, rules, actions, results.
- Watch it: write frames to `<trace>.live.png` (see `NovaGame(live_frame=...)`) and run `jevbrief view --live <trace>`.

## Done when

- [ ] The ROM's license is confirmed and quoted; no ROM is in the repo
- [ ] `verify_<game>.py` passes on the real game
- [ ] State sent to Jev has no raw numbers; every drop has a reason code
- [ ] `check_adapter` and one test per reason code pass; the full suite passes
- [ ] A real run plays in the live viewer, and the benchmark results are written with caveats
