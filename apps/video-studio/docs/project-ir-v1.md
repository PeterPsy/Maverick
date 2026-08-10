# Project IR v1 normative profile

`video-project-ir.v1` is the renderer-independent authority for a Video Studio
project. The JSON Schema is `schemas/project-ir.v1.schema.json`; Python models
and semantic validators live under `backend/project_ir/`. A document is valid
only when it satisfies both layers.

## Document model

The root has exactly `ir_version`, `metadata`, `canvas`, `frame_rate`, `audio`,
`duration_frames`, `assets`, and `timeline`.

- Metadata binds one project and workspace and carries bounded plain tags and
  declarative provenance.
- Canvas uses positive integer pixels, reduced rational pixel aspect, an
  allowlisted background/color-space profile, and no renderer settings.
- Audio declares an allowlisted integer sample rate and channel layout.
- Assets identify Storage records by `storage_file_id`, `source_version`, and
  SHA-256. Provenance names a governed provider interface and the same trusted
workspace. Source timing declares duration PTS, reduced time base, duration
  microseconds equal to the explicit PTS/time-base conversion, frame-rate mode,
  and a strictly ordered, source-bounded VFR PTS map when applicable.
- Timeline arrays preserve declared order. Track and clip kinds must be
  compatible. Same-track clip intervals are half-open `[start, start+duration)`
  and may touch but not overlap.
- Transform/audio authority uses named integer fixed-point units such as
  millipixels, permille, millidegrees, millibels, and milli-pan.
- Effects, transitions, easing, fonts, fit/compositing, color spaces, and
  templates resolve through versioned allowlists. Effect parameters are checked
  against their registered typed schema.

## Exact temporal arithmetic

For frame rate `N/D`, timeline frame `f` maps to microseconds as the exact
rational:

```text
frame_us = f * D * 1_000_000 / N
```

For source PTS `p` and time base `Tn/Td`:

```text
pts_us = p * Tn * 1_000_000 / Td
```

For sample rate `S`:

```text
sample_us = sample * 1_000_000 / S
```

Inverse conversions preserve the same rational numerator/denominator until a
declared integer boundary. Supported rounding policies are `floor`, `ceil`,
`toward-zero`, and `nearest-ties-to-even`; nearest-ties-to-even is the default.
Negative rounding follows the mathematical policy, not language truncation.

Conversions do not feed a previously rounded result back as authority. Frame,
PTS, and sample boundaries are independently derived from their original exact
rational values. This prevents cumulative drift on long timelines and repeated
conversions. VFR media resolves frame index to PTS, and PTS to the active frame,
directly against its source-bounded monotonic map rather than pretending the
source has a constant frame rate. Timeline placement remains integer-frame
authority at the project rate.

## Invariants

After canonical byte and complexity limits pass, validation returns deterministic
issues sorted by path/code. Resource-limit failures stop before schema traversal,
security scanning, indexing, or semantic work. Validation checks:

- globally unique bounded identifiers and all referenced endpoints;
- non-negative project/source intervals and positive clip durations;
- project containment, source-duration bounds, same-track non-overlap, and
  source in/out ordering;
- transitions on compatible ordered clips with bounded duration/handles;
- unique, ordered, in-clip keyframes and audio envelope points;
- track/clip kind, asset/clip kind, channel, font, template, transition,
  effect, easing, fit, compositing, and color-space compatibility;
- acyclic groups, bidirectional unique membership, and valid group/relationship
  members;
- workspace-local asset provenance and governed provider identity;
- configured document and collection complexity limits.

## Security profile

Project IR is data, never code. The structural profile rejects undeclared
fields, and the recursive security scan rejects keys or values that introduce:

- scripts, expressions, active HTML/markup, arbitrary shader source, or shell
  commands;
- credentials, passwords, secrets, API keys, or tokens;
- remote, data, file, FTP, or SSH URLs;
- absolute host paths, home paths, Windows drive paths, or traversal segments;
- direct references to another workspace or another app's private files.

Text is plain Unicode text with control-character and surrogate restrictions.
Canonical integer authority is limited to the portable JSON safe-integer range,
and nesting is bounded at 64 levels. Renderer
implementations must consume validated registry IDs and typed parameters; they
must not reinterpret text or metadata as executable content.

## Complexity defaults

The default canonical document limit is 2,000,000 bytes. Collection defaults
are 128 tracks, 10,000 clips, 20,000 layers, 100,000 keyframes, 50,000 effects,
20,000 transitions, 100,000 captions, 20,000 markers, 10,000 groups, and
500,000 counted text characters. Hosts may supply stricter positive limits.
