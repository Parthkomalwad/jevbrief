# android adapter benchmark

Run on 2026-09-26 with `jev-1.13.0`: 107 real taps from 40 episodes of Google's [AndroidControl](https://github.com/google-research/google-research/tree/master/android_control) dataset (Apache 2.0), collected by `fetch_androidcontrol.py`. 3 runs per task and arm, 642 calls in all.

**Question:** which element on the screen should be tapped next? **Goal:** the dataset's step instruction, such as "Click on the search icon" or "Tap on the three dots icon of Venice tour document". **Right answer:** the element the person tapped: the smallest interactive element under the tap point, plus near-identical wrappers.

| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |
|---|---|---|---|---|---|
| raw | 55% (176/321), 48 errors | 17308 | 440 | 0.91 | 171 |
| jevbrief | 85% (273/321) | 1813 | 320 | 0.95 | 20 |

| Baseline (no model call) | Accuracy |
|---|---|
| random element among the ones jevbrief keeps | 6% (expected) |
| the element jevbrief's rules score highest | 37% (40/107) |

Per task: jevbrief was right more often than raw on 36 tasks, and raw more often than jevbrief on 4. Both were right every time on 54, both wrong every time on 12, and on 1 task raw was right 2 of 3 times and jevbrief 3 of 3.

## Notes

- **Real data.** The screens, instructions, and taps are real recordings from 40 episodes across many apps, including Gmail, Google Drive, Calendar, Maps, eBay, Amazon, travel booking, fitness, and learning apps. They are the first 40 episodes of the dataset's first file. Screenshots are not used: both arms see only the element tree.
- **Labels were hand-reviewed and frozen before the run** (b044fcc). The collector labels all taps automatically, and each was checked against its instruction. One task was dropped: its tap landed on a menu drawer, and the label picked the calendar cell underneath. `tasks.json` records the review in `review`.
- **The raw arm's errors are real limits, not bad luck.** Every error (48) is Jev's input token limit: 16 of the 107 screens have too many elements to send whole. Counting only the calls that fit, raw scores 64% (176/273), against 85% for jevbrief over every call.
- **Where jevbrief cannot win.** On 3 tasks the rules drop the tapped element, so those count against it:
  - two taps on elements the recording marks hidden or disabled (stale flags in the data)
  - one tap on a row's "more" icon that is identical on every row, where position words cannot tell the rows apart
- **Step instructions are the easier question.** Each goal names the element to tap, so this measures finding the element (grounding), not planning a task. With only the episode goal ("share the document with Karin"), the right tap is often ambiguous without the steps taken so far. That is a different benchmark.
- **The adapter was fixed on this data before the run.** Reviewing the labels exposed four bugs, fixed and tested before the labels were frozen:
  - rows in flat element lists were not labeled from the text inside them
  - icons without text did not use their resource ID
  - icon-font glyphs were read as labels
  - identical buttons in different places were dropped as duplicates

  So the result above is measured on the data the adapter was tuned on. The holdout below is the check.
- **Small, one file.** 107 taps from 40 episodes. The screens are not committed: `fetch_androidcontrol.py` downloads them again. It streams the start of one 2.5 GB file and stops after the episodes it needs.

## Holdout: fresh data, adapter unchanged

To check that the fixes above did not simply fit this data, 40 more episodes were collected from a different file of the dataset (`--shard 1`, `tasks_shard1.json`), **with the adapter unchanged**. 105 taps were hand-reviewed, two mislabeled taps were dropped, and the labels were frozen (05bf02e) before the run.

| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |
|---|---|---|---|---|---|
| raw | 61% (192/315), 24 errors | 18753 | 458 | 0.94 | 153 |
| jevbrief | 84% (265/315) | 2049 | 341 | 0.97 | 22 |

| Baseline (no model call) | Accuracy |
|---|---|
| the element jevbrief's rules score highest | 32% (34/105) |

- **The result holds:** jevbrief scored 84% on fresh data, against 85% on the tuning data. Per task, it was right more often than raw on 29 tasks and less often on 4. Both were right every time on 59, and both wrong every time on 13.
- **Raw:** 24 errors, from 8 screens over Jev's token limit. Counting only the calls that fit, raw scores 66% (192/291).
- **Unlabeled taps on fresh data:** 9 of 116 taps (8%) were on elements with no text, no description, no ID, and no text inside, so they could not be labeled. The collector skipped them, but an agent on those screens would face them.

## Per task (tuning data)

| Task | raw | jevbrief |
|---|---|---|
| 0_2: Go to the Past section | 3/3 | 3/3 |
| 20_1: Click on the Mobile category at the top  | 0/3 | 3/3 |
| 20_2: close the pop up | 0/3 | 3/3 |
| 60_1: Click on the search bar | 0/3 | 0/3 |
| 80_1: Select the Strava mail  | 0/3 | 0/3 |
| 80_2: Click on the Mark as unread icon to unma | 3/3 | 3/3 |
| 100_0: Click on the three dots next to the agen | 3/3 | 3/3 |
| 100_1: Click on the make available offline opti | 0/3 | 3/3 |
| 140_1: Long press on the "the Queen's Gambit" b | 0/3 | 0/3 |
| 140_2: Click on the more options icon at the to | 3/3 | 3/3 |
| 140_3: Click on the tab "share". | 0/3 | 3/3 |
| 140_4: Click on the tab See all. | 0/3 | 3/3 |
| 160_1: Tap on the home option at the bottom lef | 3/3 | 3/3 |
| 160_2: Tap on the three dots icon of Oscar and  | 3/3 | 3/3 |
| 160_3: Tap on the share option | 3/3 | 3/3 |
| 160_4: Select the gmail option at the bottom le | 0/3 | 3/3 |
| 220_2: Click on the I DON'T WANT TO AVAIL THIS  | 3/3 | 3/3 |
| 220_4: Click on the running icon in the Other T | 0/3 | 0/3 |
| 220_5: Click on the Stats icon | 3/3 | 3/3 |
| 240_6: Click on the painting present on the scr | 0/3 | 0/3 |
| 240_8: Tap on the Add to Cart option present at | 0/3 | 3/3 |
| 260_0: Click on the Select Products option to a | 3/3 | 3/3 |
| 260_1: Click on the Add Selected Items at the b | 3/3 | 3/3 |
| 260_2: Click on the M option to select the size | 3/3 | 3/3 |
| 260_3: Click on the Add Selected Items at the b | 3/3 | 3/3 |
| 281_0: close the current event | 0/3 | 0/3 |
| 281_1: click on search bar | 3/3 | 3/3 |
| 281_3: click on search icon | 3/3 | 3/3 |
| 281_4: select birthday event on 16 jun  | 3/3 | 0/3 |
| 321_1: Click on the cross icon of the search ba | 3/3 | 3/3 |
| 321_2: Click on the search bar at the top of th | 3/3 | 3/3 |
| 321_4: Click on the search icon at the bottom r | 0/3 | 3/3 |
| 321_5: Click on the layers icon to apply the tr | 3/3 | 3/3 |
| 341_1: Click on the forward toggle button at th | 3/3 | 3/3 |
| 341_2: Click on the forward toggle button at th | 3/3 | 3/3 |
| 341_3: Click on activities. | 0/3 | 3/3 |
| 341_4: Click on the search box at the top | 3/3 | 3/3 |
| 361_1: click on the check box of Microsoft trai | 0/3 | 3/3 |
| 381_0: Click on Log out on the left side of the | 3/3 | 3/3 |
| 381_1: Click on yes in the middle right of the  | 3/3 | 3/3 |
| 421_1: Click on the drop down icon next to the  | 0/3 | 3/3 |
| 421_4: Click on the see more reviews button | 0/3 | 3/3 |
| 442_0: click on search bar | 3/3 | 3/3 |
| 442_2: click on search icon | 0/3 | 2/3 |
| 462_0: Tap on the search omio button | 3/3 | 3/3 |
| 462_1: Tap on the bus icon at the top of the sc | 3/3 | 0/3 |
| 462_2: Tap on the 1:55am -3:15am option | 0/3 | 3/3 |
| 462_3: Tap on the share icon at the top right c | 3/3 | 3/3 |
| 482_0: Click on the search icon at the top righ | 0/3 | 3/3 |
| 482_2: Click on the ocean | 0/3 | 0/3 |
| 482_3: Click on the play button | 0/3 | 0/3 |
| 502_2: Click on the search box at the top. | 3/3 | 3/3 |
| 502_4: Click on the search icon at the bottom r | 3/3 | 3/3 |
| 522_0: Click on the arrow icon at the top left  | 3/3 | 3/3 |
| 522_1: Click on Grocery list file on the right  | 0/3 | 0/3 |
| 542_8: click on the first search result of trai | 0/3 | 3/3 |
| 542_9: click on the Amtrak of operators section | 0/3 | 3/3 |
| 562_1: Click on the search bar at the top of th | 3/3 | 3/3 |
| 562_3: Click on first option at the top of the  | 0/3 | 0/3 |
| 562_5: Click on Filter on the right side of the | 3/3 | 3/3 |
| 562_6: Click on Brand in the middle of the scre | 0/3 | 3/3 |
| 582_1: Click on the three dots at the top right | 3/3 | 3/3 |
| 582_2: Click on the share icon | 0/3 | 3/3 |
| 582_3: Click on the gmail option  | 0/3 | 3/3 |
| 582_5: Click on the send icon  | 3/3 | 3/3 |
| 602_0: Click on the Rotterdam Centraal tab. | 0/3 | 3/3 |
| 622_1: Click on Flights. | 0/3 | 3/3 |
| 622_2: Click on One-way. | 3/3 | 3/3 |
| 622_3: Click on Delhi. | 3/3 | 3/3 |
| 622_4: Click on cancel. | 0/3 | 0/3 |
| 642_3: click on the Vocabulary option | 0/3 | 3/3 |
| 642_4: click on the Start now button at the bot | 3/3 | 3/3 |
| 642_5: select the Basic option | 3/3 | 3/3 |
| 642_6: click on the Star now button at the bott | 3/3 | 3/3 |
| 662_1: Click on the search icon at the bottom. | 3/3 | 3/3 |
| 662_3: Click on the Search icon at the bottom r | 0/3 | 3/3 |
| 662_4: Click on the tab "Lenardo da vinci". | 3/3 | 3/3 |
| 702_1: Click on the search bar the top of the s | 3/3 | 3/3 |
| 702_2: Click on the upper east side | 0/3 | 3/3 |
| 702_3: Click on the share button | 3/3 | 3/3 |
| 702_4: Click on the Cole | 0/3 | 3/3 |
| 743_0: Click on the tHmesto TH-T08 8in Combinat | 0/3 | 3/3 |
| 743_3: Click on all details | 0/3 | 3/3 |
| 743_4: Click on the specification | 3/3 | 3/3 |
| 763_1: Click on the Three bar menu icon at the  | 3/3 | 3/3 |
| 763_4: Click on the Events to change the color  | 0/3 | 3/3 |
| 763_5: Click on the color option to change the  | 0/3 | 3/3 |
| 783_1: click on Allow | 3/3 | 1/3 |
| 783_2: click on the search icon | 0/3 | 3/3 |
| 783_4: click on the search icon | 3/3 | 3/3 |
| 803_0: Click on the three bar menu at the top l | 3/3 | 3/3 |
| 803_1: Go to the thrash | 2/3 | 3/3 |
| 803_2: Click on the three-dot icon of Financial | 3/3 | 3/3 |
| 803_3: Click on the restore option | 0/3 | 3/3 |
| 823_0: Tap on the menu icon at the top left cor | 3/3 | 3/3 |
| 823_1: Select the month option | 0/3 | 3/3 |
| 843_1: Click on the search bar to look up the p | 3/3 | 3/3 |
| 843_3: Select India gate basmati rice 5 kg from | 3/3 | 3/3 |
| 843_6: Select the first option from the search  | 0/3 | 0/3 |
| 843_9: Click on the Add to cart button at the b | 0/3 | 3/3 |
| 883_1: Go to the Book tab | 3/3 | 3/3 |
| 883_2: Click on the From text bar | 3/3 | 3/3 |
| 883_4: Click on the first search suggestion | 0/3 | 3/3 |
| 883_6: Click on the first search suggestion | 0/3 | 3/3 |
| 903_0: Tap on the three dots icon of Venice tou | 3/3 | 0/3 |
| 903_1: Select the gmail option | 3/3 | 3/3 |
| 903_2: Tap on the share as file button | 3/3 | 3/3 |
