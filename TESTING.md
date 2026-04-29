# Manual Test Procedure

Run all tests with: `source .venv/bin/activate && ltpi practice /tmp/safm.mp3 guitar`

Unless otherwise noted, start each section from a fresh launch.

## 1. Basic playback

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Launch | Audio plays immediately. Status shows `▶`, position advances, speed 50%, pitch 0c, loop OFF, mode solo, part guitar |
| 1.2 | Press SPACE | Audio pauses. Status shows `⏸`. Position stops advancing |
| 1.3 | Press SPACE | Audio resumes from where it paused |
| 1.4 | Let it play to the end | Audio stops. Status shows `⏸` at final position |
| 1.5 | Press 0 while paused | Position resets to 0.0s. Stays paused |
| 1.6 | Press SPACE | Audio plays from beginning |
| 1.7 | Press 0 while playing | Position resets to 0.0s. Continues playing |
| 1.8 | Press Q | Player exits cleanly, terminal restored to normal |

## 2. Speed control

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Press SPACE to pause | Paused |
| 2.2 | Press X twice | Speed shows 30%. Status shows "(stretching...)" during processing. No audio (paused) |
| 2.3 | Press SPACE to resume | Audio plays at 30% speed (noticeably slower, pitch unchanged) |
| 2.4 | Press W three times | Speed shows 60%. Status shows "(stretching...)" during each re-stretch, then resumes. Position doesn't jump back |
| 2.5 | Press W repeatedly until 150% | Speed caps at 150%, further W presses are no-ops |
| 2.6 | Press X repeatedly until 20% | Speed caps at 20%, further X presses are no-ops |

## 3. Pitch control

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | Press E | Pitch shows +10c. Status shows "(pitch-shifting...)" then audio resumes pitched slightly up |
| 3.2 | Press E again | Pitch shows +20c. Audibly higher than original |
| 3.3 | Press C three times | Pitch shows -10c. Audio pitched slightly below original |
| 3.4 | Verify position | Position should not jump; continues from where it was |

## 4. Seek and nudge

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | Press D | Position jumps forward ~5s |
| 4.2 | Press D repeatedly | Position continues advancing 5s per press |
| 4.3 | Press A | Position jumps back ~5s |
| 4.4 | Press A at position < 5s | Position clamps to 0.0s, doesn't go negative |
| 4.5 | Press D near end of track | Position clamps to end, doesn't overflow |
| 4.6 | Press SPACE to pause, then V | Position advances 0.05s (fine nudge forward) |
| 4.7 | Press Z | Position goes back 0.05s (fine nudge backward) |
| 4.8 | Press Z at position 0.0s | Position stays at 0.0s, doesn't go negative |

## 5. Mode cycling

| Step | Action | Expected |
|------|--------|----------|
| 5.1 | Start in solo mode | Hear only the guitar part |
| 5.2 | Press S | Mode shows "mute". Hear everything EXCEPT guitar (play-along mode) |
| 5.3 | Press S | Mode shows "mix". Hear full mix including guitar |
| 5.4 | Press S | Mode shows "solo" again. Back to guitar only |
| 5.5 | Verify position | Position should not jump on mode change |

## 6. Loop

| Step | Action | Expected |
|------|--------|----------|
| 6.1 | Play until ~20s, press [ | Status shows `loop: OFF 20.0s-?` (approx) |
| 6.2 | Play until ~30s, press ] | Status shows `loop: OFF 20.0s-30.0s` (approx) |
| 6.3 | Press L | Status shows `loop: ON`. If position was past 30s, jumps back to 20s |
| 6.4 | Let it play | Audio loops between 20s and 30s repeatedly |
| 6.5 | Press L | Status shows `loop: OFF`. Audio continues past 30s normally |
| 6.6 | Press L again | Loop re-enabled, jumps back into region if needed |
| 6.7 | Press [ at 50s | Loop start moved to 50s. End cleared (was 30s < 50s). Loop deactivated. Status shows `loop: OFF 50.0s-?` |
| 6.8 | Press ] at 40s (before start) | End set to 40s but < start (50s), so start cleared. Status shows `loop: OFF ?-40.0s` |

## 7. Loop + seek/nudge interaction

| Step | Action | Expected |
|------|--------|----------|
| 7.1 | Set a loop (20s-30s) and enable it | Looping |
| 7.2 | Press A/D | Position moves but stays clamped within 20s-30s |
| 7.3 | Press A at loop start | Position stays at 20s, doesn't go below |
| 7.4 | Press D at loop end | Position stays at ~30s, doesn't exceed |
| 7.5 | Press Z/V | Fine nudge also clamped within loop region |
| 7.6 | Press 0 while loop is active | Position jumps to loop start (20s), not song start |
| 7.7 | Press L to disable loop, then press 0 | Position jumps to song start (0.0s) |

## 8. Loop + speed interaction

| Step | Action | Expected |
|------|--------|----------|
| 8.1 | Set a loop and enable it | Looping at some speed |
| 8.2 | Press W or X to change speed | After re-stretch, playback resumes inside the loop region. Position doesn't jump outside the loop |
| 8.3 | Verify loop boundaries | Loop still corresponds to the same section of the song (same musical content) |

## 9. Loop point precision (nudge workflow)

| Step | Action | Expected |
|------|--------|----------|
| 9.1 | Play to roughly where you want the loop start | Near the target |
| 9.2 | Press SPACE to pause | Paused |
| 9.3 | Press Z/V to nudge to exact position | Position changes by 0.05s per press |
| 9.4 | Press [ | Loop start set at precise position |
| 9.5 | Press SPACE, play to near loop end | Near the end target |
| 9.6 | Press SPACE, nudge with Z/V | Fine-tune end position |
| 9.7 | Press ] | Loop end set at precise position |
| 9.8 | Press L | Loop activates. Loops precisely between the two nudged points |

## 10. Hold

| Step | Action | Expected |
|------|--------|----------|
| 10.1 | Play until an interesting note, press H | Status shows `⏺`. A short slice of audio repeats continuously |
| 10.2 | Press E or C while holding | Pitch changes audibly on the held note (brief silence during rebuild) |
| 10.3 | Press W or X while holding | Speed changes audibly on the held note |
| 10.4 | Press H again | Hold released. Playback resumes from where hold was activated. Status shows `▶` |

## 11. play-along command

Launch with: `ltpi play-along /tmp/safm.mp3 guitar`

| Step | Action | Expected |
|------|--------|----------|
| 11.1 | Launch | Audio plays at 100% speed in mute mode (everything except guitar). Status shows speed 100%, mode mute |
| 11.2 | All other controls | Work the same as in practice mode |

## 12. Separation and caching

| Step | Action | Expected |
|------|--------|----------|
| 12.1 | `ltpi separate /tmp/safm.mp3` (already separated) | Prints "Stems already exist", lists 6 stems |
| 12.2 | `ltpi parts /tmp/safm.mp3` | Lists: vocals, drums, bass, guitar, piano, other |
| 12.3 | `rm -rf stems/safm && ltpi practice /tmp/safm.mp3 bass` | Auto-separates (takes a few minutes), then enters player |

## 13. Error cases

| Step | Action | Expected |
|------|--------|----------|
| 13.1 | `ltpi separate nonexistent.mp3` | Error message about file not found (from Click) |
| 13.2 | `ltpi practice /tmp/safm.mp3 banjo` | Error message about invalid choice (from Click) |
