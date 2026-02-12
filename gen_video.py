import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed:\n{' '.join(cmd)}\n\nSTDERR:\n{p.stderr}")

def ffprobe_json(path: str) -> dict:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}:\n{p.stderr}")
    return json.loads(p.stdout)

def get_video_props(video_path: str):
    meta = ffprobe_json(video_path)
    vstreams = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
    if not vstreams:
        raise ValueError(f"No video stream found: {video_path}")
    vs = vstreams[0]
    width = int(vs["width"])
    height = int(vs["height"])
    r = vs.get("r_frame_rate", "30/1")
    num, den = r.split("/")
    fps = float(num) / float(den) if float(den) != 0 else 30.0
    return width, height, fps

def list_videos(folder: Path, recursive: bool):
    if recursive:
        files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    else:
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    # 재현 가능성을 위해 기본 정렬(셔플 전)
    return sorted(files, key=lambda p: p.name.lower())

def extract_first_frame(first_video: str, frame_png: str):
    run(["ffmpeg", "-y", "-i", first_video, "-vf", "select=eq(n\\,0)", "-vframes", "1", frame_png])

def make_intro_from_frame(frame_png: str, intro_audio: str, out_path: str,
                          width: int, height: int, fps: float, duration_sec: float = 3.0):
    # 3초 고정 이미지 + 음성 (audio가 짧으면 apad로 3초까지 채움)
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{duration_sec}", "-i", frame_png,
        "-i", intro_audio,
        "-vf", f"scale={width}:{height},setsar=1,fps={fps},format=yuv420p",
        "-af", f"apad=pad_dur={duration_sec}",
        "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        out_path
    ])

def normalize_clip(in_path: str, out_path: str, width: int, height: int, fps: float):
    # 모든 클립을 같은 스펙으로 맞춰서 concat copy가 되게끔
    run([
        "ffmpeg", "-y",
        "-i", in_path,
        "-vf", f"scale={width}:{height},setsar=1,fps={fps},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        out_path
    ])
def concat_demuxer(file_list: list[str], output_path: str, reencode_fallback: bool = True):
    list_txt = Path(output_path).with_suffix(".concat.txt")

    with open(list_txt, "w", encoding="utf-8") as f:
        for p in file_list:
            # ffmpeg concat list: single quotes inside path must be escaped like: ' -> '\''
            safe = p.replace("'", "'\\''")
            f.write("file '{}'\n".format(safe))

    # 1) 빠르게 copy 시도
    try:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_txt), "-c", "copy", output_path])
        return
    except Exception:
        if not reencode_fallback:
            raise
        # 2) 실패하면 재인코딩 concat
        run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_txt),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            output_path
        ])

def main():
    ap = argparse.ArgumentParser(description="Shuffle-merge all videos in a folder with 3s intro still+voice and fixed outro.")
    ap.add_argument("--folder", required=True, help="Folder containing videos.")
    ap.add_argument("--intro-audio", required=True, help="Audio for the 3-second intro (mp3/wav/m4a).")
    ap.add_argument("--outro", required=True, help="Fixed outro video to append at the end.")
    ap.add_argument("--output", required=True, help="Output merged video path (e.g., out.mp4).")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducible shuffle.")
    ap.add_argument("--recursive", action="store_true", help="Include subfolders.")
    ap.add_argument("--max", type=int, default=None, help="Use only first N videos after shuffle (optional).")
    ap.add_argument("--tmpdir", default=".tmp_shuffle_merge", help="Temporary directory.")
    args = ap.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        print(f"Folder not found: {folder}", file=sys.stderr)
        sys.exit(1)

    intro_audio = str(Path(args.intro_audio).expanduser().resolve())
    outro = str(Path(args.outro).expanduser().resolve())
    output = str(Path(args.output).expanduser().resolve())

    vids = list_videos(folder, recursive=args.recursive)
    if not vids:
        print(f"No video files found in: {folder}", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(args.seed)
    rng.shuffle(vids)

    if args.max is not None and args.max > 0:
        vids = vids[:args.max]

    # 셔플 결과 로그
    print("Shuffled order:")
    for i, p in enumerate(vids, 1):
        print(f"{i:02d}. {p.name}")

    tmpdir = Path(args.tmpdir)
    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir(parents=True, exist_ok=True)

    first_video = str(vids[0])
    width, height, fps = get_video_props(first_video)

    frame_png = str((tmpdir / "first_frame.png").resolve())
    intro_clip = str((tmpdir / "00_intro.mp4").resolve())

    extract_first_frame(first_video, frame_png)
    make_intro_from_frame(frame_png, intro_audio, intro_clip, width, height, fps, duration_sec=3.0)

    normalized = []

    # intro
    intro_norm = str((tmpdir / "norm_00_intro.mp4").resolve())
    normalize_clip(intro_clip, intro_norm, width, height, fps)
    normalized.append(intro_norm)

    # shuffled videos
    for idx, vp in enumerate(vids, start=1):
        outp = str((tmpdir / f"norm_{idx:02d}_in.mp4").resolve())
        normalize_clip(str(vp), outp, width, height, fps)
        normalized.append(outp)

    # fixed outro always last
    outro_norm = str((tmpdir / f"norm_{len(vids)+1:02d}_outro.mp4").resolve())
    normalize_clip(outro, outro_norm, width, height, fps)
    normalized.append(outro_norm)

    concat_demuxer(normalized, output, reencode_fallback=True)

    print(f"\n✅ Done: {output}")
    print(f"Temp: {tmpdir}")

if __name__ == "__main__":
    main()
