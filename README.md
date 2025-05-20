Python script for cutting videos into segments of specified duration using FFmpeg.

Key features:
- Cut videos into segments of customizable length (default: 2 minutes)
- Preserve original video and audio quality using stream copying
- Automatically detect video duration
- Save segments to specified output directory
- Handle various video formats and codecs
- Efficient processing with minimal CPU usage

Technical details:
- Uses FFmpeg directly via subprocess for reliable audio handling
- Implements proper timestamp management with -avoid_negative_ts
- Includes FFmpeg availability checking
- Preserves all audio channels and codecs

Usage:
python video_cutter.py input_file output_dir -d duration_in_seconds