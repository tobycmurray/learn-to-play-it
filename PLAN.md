# PLAN: Beat Detection, Click Track, and Transcription Pipeline for `ltpi`

## Overview

This document describes two layers of new functionality:

1. **Beat detection + click track** — useful standalone for practice,
   and a prerequisite for everything below
2. **Transcription pipeline** — turns stems into MIDI, notation, and tab

Pipeline (full):

    audio → stems → beat detection → MIDI → comparison →
    quantization → tab (or score)

Principles:

- modular CLI stages
- cached artifacts
- inspectable outputs
- user override at every stage
- iterative refinement over one-shot automation

For piano or other non-fretted instruments, the pipeline is a strict
subset: skip `notes-to-tab` and export quantized MIDI directly to
MusicXML (no fingering ambiguity to resolve).

------------------------------------------------------------------------

## Phase 1: Beat Detection + Click Track

This is the first thing to build. It's valuable on its own — a
musician practicing a part benefits from a click track during silent
passages or sparse sections — and it's a prerequisite for the
quantization stage of the transcription pipeline.

### detect-beat

Estimate tempo, beats, and time signature.

    ltpi detect-beat song.mp3
    ltpi detect-beat song.mp3 --from drums   # use drum stem instead of full mix

If the detection is wrong, re-run with hints:

    ltpi detect-beat song.mp3 --bpm 120         # override tempo
    ltpi detect-beat song.mp3 --downbeat 0.42   # anchor first downbeat

Artifacts: `analysis/beats.json`, `analysis/click.wav`

```json
{
  "beats": [0.42, 0.91, 1.39, 1.88, 2.37, ...],
  "downbeats": [0.42, 1.88, 3.34, ...],
  "summary": {
    "bpm": 124.0,
    "time_signature": "3/4"
  }
}
```

The primary output is the beat and downbeat *positions* — actual
timestamps throughout the song. These track natural tempo drift,
rubato, and feel in live or older recordings. The click track is
rendered from these positions, not from a fixed BPM + offset.

BPM and time signature are derived summary statistics (median inter-beat
interval → BPM; beats between downbeats → meter). Useful for display
but not authoritative — the positions are the ground truth.

Confidence reporting:

- report overall confidence score
- flag specific regions where beat tracking is uncertain (tempo
  changes, breaks, irregular sections)
- if confidence is low, suggest user enable the click track in practice
  mode to verify aurally

Implementation:

- beat_this (CPJKU, ISMIR 2024) — transformer-based beat and downbeat
  tracker; state-of-the-art accuracy, actively maintained, no madmom
  dependency; already shares PyTorch with Demucs
- default input: original audio (full mix) — beat_this is trained on
  full mixes and handles intros, breaks, and drumless sections
- optional `--from <stem>` override if the user finds a specific stem
  gives better results in their case
- click track: synthesize short percussive tones at each detected beat
  position (accented on downbeats), write to WAV
- BPM and time signature derived from positions as summary stats

### Click track in practice/play-along modes

Once `detect-beat` has been run for a song, the player can overlay a
click track during practice and play-along sessions.

    ltpi practice song.mp3 guitar --click
    ltpi play-along song.mp3 guitar --click

Implementation:

- synthesize short percussive tones at detected beat times (accented
  on downbeats, lighter on beats)
- mix into audio stream at playback time, respecting current speed
- toggle on/off with a key binding (same as other player controls)
- if the click sounds wrong, the grid is wrong — re-run detect-beat
  with hints (`--bpm`, `--downbeat`)

Grid verification happens implicitly: the user hears whether the click
aligns while practicing. No separate verification command needed.

------------------------------------------------------------------------

## Phase 2: Transcription Pipeline

Everything below assumes Phase 1 is complete — `detect-beat` exists
and the player supports click tracks. The grid is used in the
quantization stage to snap MIDI to notation.

------------------------------------------------------------------------

### 1. tune-stem

Estimate tuning offset.

    ltpi tune-stem song.mp3 guitar

Output: "This stem appears to be out of tune by -35 cents (confidence
0.82)"

Artifact: `analysis/guitar.tuning.json`

```json
{
  "cents_offset": -35,
  "confidence": 0.82,
  "suggested_pitch_correction": 35
}
```

Implementation:

- extract stable pitch frames (librosa.pyin or CQT)
- compute cents deviation from equal-tempered pitches
- robust median

Note: Basic Pitch is fairly robust to offsets up to ~50 cents, so this
stage may be unnecessary. Build `stem-to-midi` first and evaluate on a
range of recordings (well-tuned, detuned, old tape) before investing
here. If tuning offsets do cause problems, an alternative to a separate
analysis pass is detecting tuning from the MIDI output itself
(systematic offset in note cents). Pre-correction is most valuable when
the offset is large or when precise pitch-bend data matters downstream.

------------------------------------------------------------------------

### 2. stem-to-midi

Transcribe audio to MIDI.

    ltpi stem-to-midi song.mp3 guitar --pitch-cents +35

Artifacts: `transcription/guitar.raw.mid`,
`transcription/guitar.raw.notes.json`

Implementation:

- Spotify Basic Pitch
- apply pitch shift pre-transcription
- capture note confidence and pitch bends

Known limitations: Basic Pitch handles polyphony reasonably but
struggles with dense chords and fast arpeggios. Dense rhythm guitar
parts will likely need heavy manual editing. The `compare-midi` stage
flags these regions so the user knows where to focus.

------------------------------------------------------------------------

### 3. compare-midi

Flag regions where the MIDI transcription likely diverges from what's
actually in the stem. The goal is to direct the user's attention to
sections that need manual inspection or correction.

    ltpi compare-midi song.mp3 guitar

Artifact: `transcription/guitar.review.json`

```json
{
  "regions": [
    {
      "start": 12.4,
      "end": 15.1,
      "bar": 8,
      "confidence": 0.42,
      "reasons": ["unmatched onsets in stem", "pitch activity without MIDI notes"]
    }
  ]
}
```

Implementation — compare abstract features, not raw audio:

- **Onset comparison**: detect onsets in the stem (librosa.onset) and
  compare against MIDI note-on times. Flag regions where the stem has
  onsets that don't correspond to any MIDI event (missed notes) or MIDI
  has note-ons without a corresponding stem onset (hallucinated notes).
- **Pitch-change detection**: track pitch contour in the stem
  (librosa.pyin or CQT) and flag regions where the stem shows pitch
  movement (e.g. a new note, bend, or slide) but the MIDI is static, or
  vice versa.
- **Density flagging**: flag regions with many overlapping MIDI notes in
  a short window — these are inherently low-confidence for polyphonic
  transcription and warrant inspection.
- **Per-note confidence**: propagate Basic Pitch's per-note confidence
  scores and flag regions where average confidence drops below a
  threshold.

This deliberately avoids resynthesizing the MIDI back to audio for
spectral comparison — timbre mismatch between a synth patch and the
real recording would dominate the signal and produce false positives.

------------------------------------------------------------------------

### 4. review-midi

Interactive correction.

    ltpi review-midi song.mp3 guitar

Features:

- play stem
- play MIDI
- play both overlaid
- jump to low-confidence regions from compare-midi
- export corrected MIDI

Future:

- piano roll editor
- waveform overlay

------------------------------------------------------------------------

### 5. quantize-midi

Convert raw MIDI to notation-ready form.

    ltpi quantize-midi song.mp3 guitar
    ltpi quantize-midi song.mp3 guitar --subdivision 16   # snap to 16ths
    ltpi quantize-midi song.mp3 guitar --subdivision 12   # triplet grid

Artifact: `notation/guitar.notes.json`

```json
{
  "subdivision": 16,
  "notes": [
    { "pitch": 64, "bar": 8, "beat": 2.5, "duration": "eighth" }
  ]
}
```

Implementation:

- align MIDI to beats.json
- snap to nearest subdivisions at configurable depth
- preserve expressive timing within tolerance

The user must be able to override subdivision per-section. Swing
eighths, pushed/pulled notes, and grace notes all look like "slightly
off-grid" but mean different things. A configurable subdivision depth
(e.g. quantize to 16ths vs. triplets) handles the common cases; grace
notes may need explicit tagging in review-midi.

------------------------------------------------------------------------

### 6. notes-to-tab

Generate guitar tab (guitar-specific; skip for piano/other instruments).

    ltpi notes-to-tab song.mp3 guitar

Artifacts: `tab/guitar.tab.json`, `tab/guitar.musicxml`

Implementation:

- generate candidate (string, fret) assignments per note
- solve via dynamic programming

Cost function:

- fret movement
- string jumps
- hand stretch
- chord feasibility
- open string bonus
- phrasing continuity

------------------------------------------------------------------------

## End-to-End Command

    ltpi transcribe song.mp3 guitar

Equivalent to:

    ltpi separate song.mp3
    ltpi tune-stem song.mp3 guitar          # optional
    ltpi detect-beat song.mp3 --from drums
    ltpi stem-to-midi song.mp3 guitar --use-tuning-analysis
    ltpi compare-midi song.mp3 guitar
    ltpi quantize-midi song.mp3 guitar
    ltpi notes-to-tab song.mp3 guitar

For piano (no tab stage):

    ltpi transcribe song.mp3 piano --format musicxml

------------------------------------------------------------------------

## Artifact Layout

    stems/<song-hash>/
      analysis/
        guitar.tuning.json
        beats.json
        click.wav
      transcription/
        guitar.raw.mid
        guitar.raw.notes.json
        guitar.review.json
        guitar.edited.mid
      notation/
        guitar.notes.json
      tab/
        guitar.tab.json
        guitar.musicxml

------------------------------------------------------------------------

## Build Order

**Phase 1** (standalone value, prerequisite for Phase 2):

1. detect-beat — tempo/beat/downbeat detection
2. click track in player — mix click into practice/play-along modes

**Phase 2** (transcription pipeline, assumes Phase 1 complete):

3. stem-to-midi — everything else depends on MIDI quality
4. quantize-midi — turns raw MIDI into notation (uses grid from Phase 1)
5. compare-midi — flags problem regions for the user
6. notes-to-tab — guitar-specific; skip for piano
7. review-midi — interactive correction UI
8. tune-stem — only if empirical testing shows tuning offsets degrade
   transcription; may not be needed at all

------------------------------------------------------------------------

## Key Insights

- drums → timing
- guitar → pitch
- MIDI quality determines tab quality
- user correction is essential
- polyphonic guitar is the hardest transcription target; expect dense
  sections to need manual editing

------------------------------------------------------------------------

## Future Enhancements

- swing detection
- ML fingering model
- technique detection (bends, slides)
- GUI piano-roll editor
- DAW integration

------------------------------------------------------------------------

## Summary

A staged, user-assisted transcription pipeline that produces reliable
tab (or score) from real recordings. Piano and other non-fretted
instruments are a strict subset of the pipeline, skipping the tab
generation stage.
