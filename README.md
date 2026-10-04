# Video Cutter with Subtitles

Python script for cutting videos into segments of specified duration using FFmpeg,
optionally with perfectly synced subtitles that can be embedded or burned in.

## Features

- Cut videos into segments of any duration (`-d`, default: 2 minutes)
- **Two ways to deliver subtitles:**
  - **Embedded** (`mov_text`) as a separate subtitle track inside each segment
  - **Burned in** (`--burn`) — subtitle text is drawn into the video pixels
- **Perfectly synced subtitles**: cues are re-timed to each segment's *actual* video
  content, so they line up regardless of where the cut lands
- Automatically detect video duration, keyframes, and `.srt` files
- Fast by default: video/audio are stream-copied (no re-encode) unless you burn
- Keyframe index is cached, so re-runs into the same output directory are fast
- Works with 1080p/4K sources and multi-channel audio

## Requirements

- Python 3
- FFmpeg installed and in PATH (https://ffmpeg.org/download.html)

## Usage

### Cutting without subtitles

```
python video_cutter.py input.mp4 output_dir -d 120
```

Stream-copies the video into 120-second segments. Fastest option, no re-encoding.

### Cutting WITH subtitles (embedded track)

```
python video_cutter.py input.mp4 output_dir -d 120
```

If an `.srt` sits next to the video (e.g. `input.srt`), it is auto-detected. Each
segment gets the matching cues as an MP4 subtitle track, plus a standalone `partN.srt`.

> **Not visible in every player.** An embedded `mov_text` track is a *separate stream* —
> many phones, TV apps, web players and social-media uploaders ignore it, or require
> you to enable "Subtitles/CC" manually. If you need subtitles that show up
> *everywhere*, use `--burn` below.

### Cutting with BURNED-IN subtitles

```
python video_cutter.py input.mp4 output_dir -d 120 --burn
```

This is the mode you want for social media (TikTok, Instagram, Reels, YouTube
Shorts...) or for any player that won't show embedded tracks. The text is rendered
directly onto the video frames, so it is part of the picture and cannot be turned off.

Trade-offs of `--burn`:
- The video **must be re-encoded**, so it takes longer and uses CPU/GPU
- Output is slightly larger/lower quality than the source (control with `--crf`)
- Embedded subtitle tracks are replaced by the burned-in text

Segments that contain no subtitle cues are still fast stream-copied, so you only pay
the re-encode cost where there's actually text on screen.

### Other examples

```
# Explicit subtitle file instead of auto-detection
python video_cutter.py input.mp4 output_dir -d 120 --subtitle subs.srt

# Bigger, more readable subtitles
python video_cutter.py input.mp4 output_dir -d 120 --burn --font-size 32

# Higher quality burn (lower CRF = better quality, bigger file)
python video_cutter.py input.mp4 output_dir -d 120 --burn --crf 16

# Custom styling (any libass force_style fields)
python video_cutter.py input.mp4 output_dir -d 120 --burn \
  --style "FontName=Impact,FontSize=28,PrimaryColour=&H00FFFFFF,Outline=2"

# Write standalone .srt files only, don't embed them
python video_cutter.py input.mp4 output_dir -d 120 --no-mux
```

## Options

| Option            | Description                                                                 |
|-------------------|-----------------------------------------------------------------------------|
| `input_file`      | Path to the input video file                                                |
| `output_dir`      | Directory to save the output segments (created if missing)                  |
| `-d, --duration`  | Duration of each segment in seconds (default: 120)                          |
| `--subtitle FILE` | Path to an `.srt` file; otherwise auto-detected next to the video           |
| `--burn`          | Hardcode subtitles onto the video frames (re-encodes; for social media)      |
| `--no-mux`        | Write standalone `.srt` files per segment but do not embed them             |
| `--encoder`       | `auto` (default, tries Intel Quick Sync then libx264), `libx264`, `h264_qsv` |
| `--crf`           | Video quality for `--burn` (lower = better, default: 18)                    |
| `--font-size`     | Subtitle font size in pixels for `--burn` (default: 18)                     |
| `--style`         | Full libass `force_style` override for `--burn`                             |

## How subtitle sync works

Subtitle timing has to follow the video that actually ends up in the file, which
differs between the two modes.

### Embedded mode (stream copy)

Stream-copy cuts can only start on a video keyframe, so a segment requested at `t`
actually begins at the last keyframe at or before `t` (up to a few seconds of
pre-roll, depending on the keyframe interval). The script:

1. Scans the input once for keyframe timestamps (cached per output directory).
2. For each segment, finds the real content window `[keyframe, keyframe + duration]`.
3. Slices the source SRT to that window, shifts timestamps by the keyframe offset,
   clamps boundary cues, and renumbers them.
4. Writes `partN.srt` and optionally muxes it into the segment as `mov_text`.

Because the shift is based on the keyframe the video actually starts on — not the
requested time — subtitles stay frame-accurate at any `-d` value.

### Burned mode (re-encode)

Burned segments are re-encoded with an exact `-ss` seek, so there is no keyframe
pre-roll and the segment really does start at the requested time. Cues are sliced
against that exact window, and the video's timestamps are reset (`setpts=PTS-STARTPTS`)
before the subtitle filter runs so the text lines up with the segment-local SRT.
Audio is stream-copied and stays in sync with the video.

## Notes

- Only `.srt` subtitle files are supported currently.
- Only `.srt` is auto-detected; name it after the video (e.g. `movie.srt` next to
  `movie.mp4`) or pass `--subtitle` explicitly.
- Subtitles already embedded in the source video are **not** carried over. The script
  maps only the video and audio streams (`-map 0:v -map 0:a`) and handles subtitles
  itself, so your `.srt` is the single source of truth and you never end up with two
  competing subtitle tracks.
- A source with **no audio stream** will fail with `-map 0:a`; add audio or use `--burn`
  on a video that has some.
- In embedded (non-burn) mode, segments may be slightly longer than `-d` due to
  keyframe pre-roll and audio padding. This is inherent to lossless stream copying.
- `--burn` re-encodes only the segments that actually contain cues, so it is much
  faster than a full re-encode of the whole video.