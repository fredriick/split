# Video Cutter with Subtitles

Python script for cutting videos into segments of specified duration using FFmpeg,
optionally with perfectly synced subtitles.

## Features

- Cut videos into segments of any duration (`-d`, default: 2 minutes)
- **Perfectly synced subtitles**: subtitles are re-timed to each segment's *actual*
  video content (cut segments start at the nearest keyframe, so the script compensates
  for that pre-roll when slicing subtitle cues)
- Deliver subtitles two ways:
  - **Embedded** into each segment as an MP4 `mov_text` subtitle track
  - **Standalone** `partN.srt` file alongside each segment
- Preserve original video and audio quality using stream copying (only the subtitle
  track is re-encoded, which is cheap)
- Automatically detect video duration, keyframes, and subtitle files
- Handle various video formats and codecs; `-map 0` keeps any embedded streams
- Keyframe index is cached, so re-runs into the same output directory are fast
- Efficient processing with minimal CPU usage

## Requirements

- Python 3
- FFmpeg installed and in PATH (https://ffmpeg.org/download.html)

## Usage

Cut without subtitles (plain video cutting, same as before):

```
python video_cutter.py input_file output_dir -d 120
```

Cut with subtitles (auto-detects an `.srt` next to the video):

```
python video_cutter.py input_file output_dir -d 120
```

Cut with an explicit subtitle file:

```
python video_cutter.py input_file output_dir -d 120 --subtitle subs.srt
```

Only write standalone `.srt` files, without embedding them into the videos:

```
python video_cutter.py input_file output_dir -d 120 --no-mux
```

## Options

| Option            | Description                                                              |
|-------------------|--------------------------------------------------------------------------|
| `input_file`      | Path to the input video file                                             |
| `output_dir`      | Directory to save the output segments                                    |
| `-d, --duration`  | Duration of each segment in seconds (default: 120)                       |
| `--subtitle FILE` | Path to an `.srt` file; otherwise auto-detected next to the video        |
| `--no-mux`        | Write standalone `.srt` files per segment but do not embed them          |

## How subtitle sync works

Stream-copy cuts can only start on a video keyframe, so a segment requested at `t`
actually begins at the last keyframe at or before `t` (up to ~a few seconds of
pre-roll, depending on the keyframe interval). The script:

1. Scans the input once for keyframe timestamps (cached per output directory).
2. For each segment, determines the real content window `[keyframe, keyframe + duration]`.
3. Slices the source SRT to that window, shifts timestamps by the keyframe offset,
   clamps boundary cues, and renumbers the cues.
4. Writes the `partN.srt` and optionally muxes it into the segment as `mov_text`.

Because the shift is based on the keyframe the video actually starts on (not the
requested time), subtitles stay frame-accurate at any `-d` value.

## Notes

- Only `.srt` subtitle files are supported currently.
- Segments may be slightly longer than `-d` (keyframe pre-roll + audio padding) and
  may briefly overlap at boundaries; this is inherent to lossless stream copying.
