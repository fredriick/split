import os
import sys
import re
import bisect
import argparse
import subprocess
import math


class FFmpegError(Exception):
    pass


def check_ffmpeg():
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def run_checked(cmd, description):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise FFmpegError(f"{description} failed:\n{stderr[-2000:]}")
    return result


def probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        return float(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def scan_keyframes(input_file, cache_path):
    size = os.path.getsize(input_file)
    mtime = os.path.getmtime(input_file)
    header = f"#size={size} mtime={mtime}"

    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            if lines and lines[0] == header:
                return [float(t) for t in lines[1:] if t]
        except (OSError, ValueError):
            pass

    print(f"Scanning keyframes of {os.path.basename(input_file)} (one-time)...")
    result = run_checked(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", input_file],
        "Keyframe scan",
    )
    keyframes = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split(",")
        if len(parts) == 2 and parts[1].startswith("K"):
            try:
                keyframes.append(float(parts[0]))
            except ValueError:
                pass
    keyframes.sort()

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(header + "\n")
            f.write("\n".join(f"{t:.6f}" for t in keyframes))
    except OSError:
        pass

    print(f"Found {len(keyframes)} keyframes.")
    return keyframes


def keyframe_before(keyframes, start):
    idx = bisect.bisect_right(keyframes, start) - 1
    if idx < 0:
        return 0.0
    return keyframes[idx]


SRT_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def srt_ts_to_seconds(ts):
    m = SRT_TIME_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Unrecognized subtitle timestamp: {ts!r}")
    h, minute, s, ms = m.groups()
    return int(h) * 3600 + int(minute) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def seconds_to_srt_ts(t):
    total_ms = int(round(max(0.0, t) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read().replace("\r\n", "\n").replace("\r", "\n")

    cues = []
    for block in text.split("\n\n"):
        lines = block.split("\n")
        ts_idx = None
        for i, line in enumerate(lines):
            if "-->" in line:
                ts_idx = i
                break
        if ts_idx is None:
            continue
        parts = lines[ts_idx].split("-->")
        try:
            start = srt_ts_to_seconds(parts[0])
            end = srt_ts_to_seconds(parts[1])
        except ValueError:
            continue
        content = "\n".join(lines[ts_idx + 1:]).strip()
        if not content:
            continue
        cues.append((start, end, content))
    return cues


def slice_cues(cues, offset, duration):
    sliced = []
    for start, end, content in cues:
        s = start - offset
        e = end - offset
        if e <= 0.0 or s >= duration:
            continue
        sliced.append((max(0.0, s), min(duration, e), content))
    return sliced


def write_srt(path, cues):
    with open(path, "w", encoding="utf-8") as f:
        for i, (s, e, content) in enumerate(cues, 1):
            f.write(f"{i}\n{seconds_to_srt_ts(s)} --> {seconds_to_srt_ts(e)}\n{content}\n\n")


def find_subtitle_file(input_file, explicit=None):
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        print(f"Subtitle file not found: {explicit}")
        return None

    base = os.path.splitext(os.path.basename(input_file))[0].lower()
    directory = os.path.dirname(input_file) or "."
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        entries = []

    srt_files = [os.path.join(directory, name) for name in entries
                 if name.lower().endswith(".srt")
                 and os.path.isfile(os.path.join(directory, name))]
    if not srt_files:
        print("No subtitle file found next to the video; cutting without subtitles.")
        return None

    for path in srt_files:
        if os.path.splitext(os.path.basename(path))[0].lower().startswith(base):
            print(f"Auto-detected subtitle file: {path}")
            return path
    sub = srt_files[0]
    print(f"Auto-detected subtitle file: {sub}")
    return sub


DEFAULT_ASS_STYLE = "FontName=Arial,FontSize={size},PrimaryColour=&H00FFFFFF,Outline=1,Shadow=0"


def escape_filter_path(path):
    # ffmpeg filtergraph on Windows: single quotes protect the value, but the
    # drive-letter ':' must still be backslash-escaped (quotes alone don't
    # protect it, and backslashes get eaten).
    path = path.replace("\\", "/").replace(":", "\\:")
    return "'" + path + "'"


def escape_filter_style(style):
    # force_style values use ',' between fields; escape all filtergraph-special
    # characters so libass receives the literal style string.
    out = []
    for ch in style:
        if ch in "\\',:;[]":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def build_copy_cut_cmd(input_file, start_time, duration, output_file):
    return ["ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", input_file,
            "-t", str(duration),
            "-map", "0",
            "-c:v", "copy",
            "-c:a", "copy",
            "-avoid_negative_ts", "1",
            output_file]


def build_burn_cmd(input_file, start_time, duration, srt_path, output_file, encoder, crf, force_style):
    vf = (f"setpts=PTS-STARTPTS,"
          f"subtitles=filename={escape_filter_path(srt_path)}"
          f":force_style={escape_filter_style(force_style)}")
    if encoder == "h264_qsv":
        vf += ",format=nv12"
    else:
        vf += ",format=yuv420p"

    cmd = ["ffmpeg", "-y",
           "-ss", str(start_time),
           "-i", input_file,
           "-t", str(duration),
           "-map", "0:v:0",
           "-map", "0:a:0",
           "-vf", vf,
           "-c:a", "copy",
           "-profile:v", "high",
           "-avoid_negative_ts", "1",
           "-movflags", "+faststart"]
    if encoder == "h264_qsv":
        cmd += ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", str(crf)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
    cmd.append(output_file)
    return cmd


def burn_video(input_file, start_time, duration, srt_path, output_file, encoder_choice, crf, force_style):
    if encoder_choice == "auto":
        encoders = ["h264_qsv", "libx264"]
    else:
        encoders = [encoder_choice]

    errors = []
    for encoder in encoders:
        try:
            os.remove(output_file)
        except OSError:
            pass
        cmd = build_burn_cmd(input_file, start_time, duration, srt_path, output_file,
                             encoder, crf, force_style)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            return encoder
        errors.append(encoder + ": " + result.stderr.decode("utf-8", errors="replace")[-300:])
    try:
        os.remove(output_file)
    except OSError:
        pass
    raise FFmpegError("Burning subtitles failed with all encoders:\n" + "\n".join(errors))


def mux_subtitles(segment_path, srt_path):
    tmp = segment_path + ".tmp.mp4"
    cmd = ["ffmpeg", "-y",
           "-i", segment_path,
           "-i", srt_path,
           "-map", "0", "-map", "1",
           "-c:v", "copy", "-c:a", "copy",
           "-c:s", "mov_text",
           "-metadata:s:s:0", "language=eng",
           "-metadata:s:s:0", "title=Subtitles",
           "-movflags", "+faststart",
           tmp]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        print(f"Warning: could not mux subtitles into {os.path.basename(segment_path)}: {stderr[-500:]}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return
    os.replace(tmp, segment_path)


def cut_video(input_file, output_dir, segment_duration, subtitle_file, no_mux,
              burn=False, encoder="auto", crf=18, force_style=None):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    base_name = os.path.basename(input_file)
    file_name, file_ext = os.path.splitext(base_name)

    print(f"Getting video information: {input_file}")
    duration = probe_duration(input_file)
    if not duration:
        print("Could not determine video duration.")
        return
    print(f"Video duration: {duration:.2f} seconds")

    num_segments = math.ceil(duration / segment_duration)
    print(f"Cutting into {num_segments} segments of {segment_duration} seconds each")

    keyframes = None
    cues = None
    if subtitle_file:
        cues = parse_srt(subtitle_file)
        print(f"Parsed {len(cues)} subtitle cues from {subtitle_file}")
        if burn:
            print("Burning subtitles into video frames...")
        else:
            cache_path = os.path.join(output_dir, f".keyframes_{file_name}.cache")
            keyframes = scan_keyframes(input_file, cache_path)
    elif burn:
        print("Warning: --burn needs a subtitle file; cutting without burning.")

    for i in range(num_segments):
        start = i * segment_duration
        if start >= duration:
            break

        output_file = os.path.join(output_dir, f"{file_name}_part{i + 1}{file_ext}")
        print(f"Creating segment {i + 1}/{num_segments}: {start:.2f}s "
              f"to {min(start + segment_duration, duration):.2f}s")
        print(f"Saving to: {output_file}")

        if burn and subtitle_file:
            seg_dur = min(start + segment_duration, duration) - start
            sliced = slice_cues(cues, start, seg_dur)
            srt_out = os.path.splitext(output_file)[0] + ".srt"
            write_srt(srt_out, sliced)
            print(f"  Subtitle track: {len(sliced)} cues -> {os.path.basename(srt_out)}")
            if sliced:
                used = burn_video(input_file, start, seg_dur, srt_out, output_file,
                                  encoder, crf, force_style)
                print(f"  Subtitles burned into video (encoder: {used})")
            else:
                run_checked(build_copy_cut_cmd(input_file, start, seg_dur, output_file),
                            f"Cutting segment {i + 1}")
                print("  No subtitle cues in this segment; fast copy cut used")
        else:
            run_checked(build_copy_cut_cmd(input_file, start, segment_duration, output_file),
                        f"Cutting segment {i + 1}")
            if subtitle_file and keyframes:
                k = keyframe_before(keyframes, start)
                seg_duration = probe_duration(output_file) or segment_duration
                sliced = slice_cues(cues, k, seg_duration)
                srt_out = os.path.splitext(output_file)[0] + ".srt"
                write_srt(srt_out, sliced)
                print(f"  Subtitle track: {len(sliced)} cues -> {os.path.basename(srt_out)}")
                if not no_mux and sliced:
                    mux_subtitles(output_file, srt_out)
                    print(f"  Subtitles muxed into segment")

        print(f"Segment {i + 1} saved successfully with audio")

    print("Video cutting completed!")


def main():
    parser = argparse.ArgumentParser(
        description="Cut a video into segments of specified duration using FFmpeg, "
                    "optionally with perfectly synced subtitles")
    parser.add_argument("input_file", help="Path to the input video file")
    parser.add_argument("output_dir", help="Directory to save the output segments")
    parser.add_argument("-d", "--duration", type=int, default=120,
                        help="Duration of each segment in seconds (default: 120 seconds = 2 minutes)")
    parser.add_argument("--subtitle", metavar="FILE",
                        help="Path to an .srt subtitle file. If omitted, an .srt next to the "
                             "input video is auto-detected")
    parser.add_argument("--no-mux", action="store_true",
                        help="Write standalone .srt files per segment but do not embed "
                             "subtitles into the video files")
    parser.add_argument("--burn", action="store_true",
                        help="Hardcode subtitles onto the video frames (re-encodes video; "
                             "required for social media uploads)")
    parser.add_argument("--encoder", choices=("auto", "libx264", "h264_qsv"), default="auto",
                        help="Encoder for --burn. 'auto' tries Intel Quick Sync (h264_qsv) and "
                             "falls back to libx264 (default: auto)")
    parser.add_argument("--crf", type=int, default=18,
                        help="Video quality for --burn (lower = better, default: 18)")
    parser.add_argument("--font-size", type=int, default=18,
                        help="Subtitle font size in pixels for --burn (default: 18)")
    parser.add_argument("--style", metavar="ASS",
                        help="Full libass force_style override for --burn, e.g. "
                             "\"FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,Outline=1\"")

    args = parser.parse_args()

    if not check_ffmpeg():
        print("FFmpeg is not installed or not in PATH.")
        print("Please install FFmpeg from https://ffmpeg.org/download.html")
        print("Make sure to add it to your system PATH.")
        sys.exit(1)

    subtitle_file = find_subtitle_file(args.input_file, args.subtitle)
    if subtitle_file and not subtitle_file.lower().endswith(".srt"):
        print("Only .srt subtitle files are supported right now.")
        subtitle_file = None

    if args.style:
        force_style = args.style
    else:
        force_style = DEFAULT_ASS_STYLE.format(size=args.font_size)

    cut_video(args.input_file, args.output_dir, args.duration, subtitle_file, args.no_mux,
              burn=args.burn, encoder=args.encoder, crf=args.crf, force_style=force_style)


if __name__ == "__main__":
    main()
