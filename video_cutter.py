import os
import sys
import argparse
import subprocess
import shutil
import tempfile

# Check if required modules are installed
try:
    import numpy
    print("NumPy successfully imported!")
except ImportError:
    print("Installing NumPy...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "numpy"])
    print("NumPy installed successfully.")

# Function to check if FFmpeg is installed
def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("FFmpeg is not installed or not in PATH.")
        print("Please install FFmpeg from https://ffmpeg.org/download.html")
        print("Make sure to add it to your system PATH.")
        return False

def cut_video_ffmpeg(input_file, output_dir, segment_duration=120):
    """
    Cut a video into segments of specified duration using FFmpeg directly.
    
    Args:
        input_file (str): Path to the input video file
        output_dir (str): Directory to save the output segments
        segment_duration (int): Duration of each segment in seconds (default: 120 seconds = 2 minutes)
    """
    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Get the base filename without extension
    base_name = os.path.basename(input_file)
    file_name, file_ext = os.path.splitext(base_name)
    
    # Get video duration using FFmpeg
    print(f"Getting video information: {input_file}")
    duration_cmd = ["ffmpeg", "-i", input_file, "-hide_banner"]
    result = subprocess.run(duration_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    
    # Parse duration from FFmpeg output
    duration_str = None
    for line in result.stderr.split('\n'):
        if "Duration:" in line:
            duration_part = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = map(float, duration_part.split(':'))
            duration_seconds = h * 3600 + m * 60 + s
            print(f"Video duration: {duration_seconds:.2f} seconds")
            break
    
    if not duration_str and not duration_seconds:
        print("Could not determine video duration.")
        return
    
    # Calculate number of segments
    num_segments = int(duration_seconds / segment_duration) + (1 if duration_seconds % segment_duration > 0 else 0)
    print(f"Cutting into {num_segments} segments of {segment_duration} seconds each")
    
    # Cut the video into segments using FFmpeg
    for i in range(num_segments):
        start_time = i * segment_duration
        
        # Generate output filename
        output_file = os.path.join(output_dir, f"{file_name}_part{i+1}{file_ext}")
        
        print(f"Creating segment {i+1}/{num_segments}: {start_time:.2f}s to {start_time+segment_duration:.2f}s")
        print(f"Saving to: {output_file}")
        
        # FFmpeg command to cut the segment with audio
        ffmpeg_cmd = [
            "ffmpeg", "-y",  # Overwrite output files without asking
            "-ss", str(start_time),  # Start time
            "-i", input_file,  # Input file
            "-t", str(segment_duration),  # Duration of segment
            "-c:v", "copy",  # Copy video codec (no re-encoding)
            "-c:a", "copy",  # Copy audio codec (no re-encoding)
            "-avoid_negative_ts", "1",  # Avoid negative timestamps
            output_file  # Output file
        ]
        
        try:
            # Run FFmpeg command
            subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(f"Segment {i+1} saved successfully with audio")
        except Exception as e:
            print(f"Error processing segment {i+1}: {e}")
    
    print("Video cutting completed!")

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Cut a video into segments of specified duration")
    parser.add_argument("input_file", help="Path to the input video file")
    parser.add_argument("output_dir", help="Directory to save the output segments")
    parser.add_argument("-d", "--duration", type=int, default=120, 
                        help="Duration of each segment in seconds (default: 120 seconds = 2 minutes)")
    
    args = parser.parse_args()
    
    # Check if FFmpeg is installed
    if not check_ffmpeg():
        sys.exit(1)
    
    # Call the cut_video function
    cut_video_ffmpeg(args.input_file, args.output_dir, args.duration)

if __name__ == "__main__":
    main() 