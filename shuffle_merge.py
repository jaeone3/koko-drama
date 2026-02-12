import json
import random
import shutil
import subprocess
import sys
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

# =========================================================
# ✅ Run with: python shuffle_merge.py
# =========================================================

ROOT_DIR = Path("./dramas")
OUTRO_VIDEO = Path("./outro.mp4")
INTRO_AUDIO_FALLBACK = Path("./intro.mp3")
INTRO_AUDIO_DIR = Path("./intro_voices")
PRE_OUTRO_AUDIO_PATH = Path("./cta_audio.mp3")
BANNER_PATH = Path("./banner.png")
BANNER_START_DELAY = 0.0
MAKE_BLACK_TRANSPARENT = True
BLACK_KEY_SIMILARITY = 0.08
BLACK_KEY_BLEND = 0.0
OUTPUT_DIR = Path("./outputs")
PICK_FOLDERS_PER_RUN = 6
MAX_VIDEOS_PER_FOLDER = 3
STATE_FILE = Path(".koko_merge_state.json")
BASE_SEED = 42
TARGET_W = 1080
TARGET_H = 1920
SCALE_MODE = "fit"
FORCE_FPS = 30.0
TMP_ROOT = Path(".tmp_shuffle_merge")
KEEP_TMP = False
VIDEO_EXTS = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"]
AUDIO_EXTS = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"]

OVERLAY_TINT_PALETTE = [
    "#00C2FF", "#FF4D6D", "#22C55E", "#F59E0B", "#A855F7", "#14B8A6", "#EF4444",
]
OVERLAY_TINT_STRENGTH = 0.85

LOOKS_7 = [
    ("clean", "eq=contrast=1.15:saturation=1.2:brightness=0.03"),
    ("warm", "colorbalance=rs=0.05:gs=0.03:bs=-0.06"),
    ("cool", "colorbalance=rs=-0.05:gs=-0.02:bs=0.06"),
    ("soft", "gblur=sigma=1.5"),
    ("crisp", "unsharp=5:5:1.5:5:5:0.0"),
    ("matte", "eq=contrast=0.9:saturation=0.85:gamma=1.1"),
    ("grain", "noise=alls=8:allf=t"),
]

SPEED_ZOOM_PRESETS = [
    {"name": "A", "zoom": 1.08, "speed": 1.03},
    {"name": "B", "zoom": 1.10, "speed": 1.05},
    {"name": "C", "zoom": 1.06, "speed": 1.07},
    {"name": "D", "zoom": 1.12, "speed": 1.02},
    {"name": "E", "zoom": 1.09, "speed": 1.06},
    {"name": "F", "zoom": 1.07, "speed": 1.04},
    {"name": "G", "zoom": 1.11, "speed": 1.03},
]


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def run(cmd: List[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    if p.returncode != 0:
        raise RuntimeError("Command failed:\n{}\n\nSTDERR:\n{}".format(" ".join(cmd), p.stderr))


def check_ffmpeg() -> None:
    for bin_name in ["ffmpeg", "ffprobe"]:
        if shutil.which(bin_name) is None:
            die(f"❌ '{bin_name}' not found.")


def ffprobe_json(path: str) -> Dict[str, Any]:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}:\n{p.stderr}")
    return json.loads(p.stdout)


def has_audio_stream(path: str) -> bool:
    meta = ffprobe_json(path)
    return any(s.get("codec_type") == "audio" for s in meta.get("streams", []))


def get_video_props(video_path: str) -> Tuple[int, int, float]:
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


def get_media_duration_seconds(path: str) -> float:
    meta = ffprobe_json(path)
    fmt = meta.get("format", {})
    dur = fmt.get("duration", None)
    if dur is None:
        for s in meta.get("streams", []):
            d = s.get("duration", None)
            if d is not None:
                return float(d)
        return 0.0
    return float(dur)


def list_files(folder: Path, exts: List[str]) -> List[Path]:
    exts_set = set(e.lower() for e in exts)
    if not folder.exists():
        return []
    return sorted(
        [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts_set],
        key=lambda p: p.name.lower()
    )


def folder_has_any_video(folder: Path) -> bool:
    exts_set = set(e.lower() for e in VIDEO_EXTS)
    if not folder.exists() or not folder.is_dir():
        return False
    return any(p.is_file() and p.suffix.lower() in exts_set for p in folder.iterdir())


def safe_stem(name: str) -> str:
    return "".join([c if c.isalnum() or c in ("-", "_") else "_" for c in name])


def load_state(state_file: Path) -> Dict[str, Any]:
    if not state_file.exists():
        return {"cycle": 1, "done": []}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        cycle = data.get("cycle", 1)
        done = data.get("done", [])
        if not isinstance(cycle, int) or not isinstance(done, list):
            return {"cycle": 1, "done": []}
        return {"cycle": max(1, cycle), "done": [str(x) for x in done]}
    except Exception:
        return {"cycle": 1, "done": []}


def save_state(state_file: Path, state: Dict[str, Any]) -> None:
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def cycle_look(cycle: int) -> Tuple[str, Optional[str]]:
    idx = (cycle - 1) % len(LOOKS_7)
    return LOOKS_7[idx]


def pick_palette_color_hex(palette: List[str], cycle: int) -> Optional[str]:
    if not palette:
        return None
    return palette[(cycle - 1) % len(palette)]


def parse_hex_color(s: Optional[str]) -> Optional[Tuple[float, float, float]]:
    if not s:
        return None
    s = s.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)
    except Exception:
        return None


def pick_intro_audio(intro_fallback: Path, intro_dir: Path, cycle: int) -> Path:
    if intro_dir.exists() and intro_dir.is_dir():
        audios = list_files(intro_dir, AUDIO_EXTS)
        if audios:
            return audios[(cycle - 1) % len(audios)]
    return intro_fallback


def get_zoom_speed_auto(cycle: int) -> Tuple[float, float, str]:
    p = SPEED_ZOOM_PRESETS[(cycle - 1) % len(SPEED_ZOOM_PRESETS)]
    print(f"🤖 Auto-selecting Preset '{p['name']}' based on Cycle {cycle}")
    return float(p["zoom"]), float(p["speed"]), p["name"]


def natural_sort_key(p: Path):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', p.name)]


def extract_first_frame(first_video: str, frame_png: str) -> None:
    cmd = ["ffmpeg", "-y", "-ss", "0.5", "-i", first_video, "-vframes", "1", "-q:v", "2", frame_png]
    try:
        run(cmd)
    except Exception:
        run(["ffmpeg", "-y", "-i", first_video, "-vframes", "1", "-q:v", "2", frame_png])


def extract_last_frame(video_path: str, frame_png: str) -> None:
    cmd = ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path, "-vsync", "vfr", "-q:v", "2", "-update", "1", "-vframes", "1", frame_png]
    try:
        run(cmd)
    except Exception as e:
        print(f"⚠️ Failed to extract last frame: {e}")


def build_base_chain(target_w: int, target_h: int, fps: float, scale_mode: str, look_filter: Optional[str], zoom: float, speed: float) -> str:
    if scale_mode == "fill":
        chain = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1"
    else:
        chain = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    chain += ",setpts=PTS-STARTPTS"
    if abs(speed - 1.0) > 1e-6:
        chain += f",setpts=PTS/{speed}"
    chain += f",fps={fps}"
    if look_filter:
        chain += "," + look_filter
    if zoom and zoom > 1.0001:
        chain += f",scale=iw*{zoom}:ih*{zoom},crop={target_w}:{target_h}"
    return chain


def overlay_tint_chains(input_label: str, out_label: str, w: int, h: int, tint_rgb: Optional[Tuple[float, float, float]], strength: float, prefix: str) -> List[str]:
    chains: List[str] = []
    ovraw = f"{prefix}ovraw"
    base_chain = f"[{input_label}]scale={w}:{h}:force_original_aspect_ratio=disable,format=rgba"
    if MAKE_BLACK_TRANSPARENT:
        base_chain += f",colorkey=0x000000:{BLACK_KEY_SIMILARITY}:{BLACK_KEY_BLEND}"
    chains.append(f"{base_chain}[{ovraw}]")
    if tint_rgb is None:
        chains.append(f"[{ovraw}]null[{out_label}]")
        return chains
    s = max(0.0, min(1.0, float(strength)))
    rr, gg, bb = tint_rgb
    mixer = f"colorchannelmixer=rr={rr}:gg={gg}:bb={bb}:aa=1"
    if s >= 0.999:
        chains.append(f"[{ovraw}]{mixer}[{out_label}]")
        return chains
    ova, ovb, ovb2 = f"{prefix}ova", f"{prefix}ovb", f"{prefix}ovb2"
    chains.append(f"[{ovraw}]split=2[{ova}][{ovb}]")
    chains.append(f"[{ovb}]{mixer}[{ovb2}]")
    chains.append(f"[{ova}][{ovb2}]blend=all_mode=normal:all_opacity={s}[{out_label}]")
    return chains


def transcode_with_optional_overlay(in_video: str, out_video: str, target_w: int, target_h: int, fps: float, scale_mode: str, look_filter: Optional[str], folder_overlay_png: Optional[str], apply_folder_overlay: bool, overlay_tint_rgb: Optional[Tuple[float, float, float]], overlay_tint_strength: float, banner_png: Optional[str], banner_delay: float, zoom: float, speed: float) -> None:
    base = build_base_chain(target_w, target_h, fps, scale_mode, look_filter, zoom, speed)
    need_audio = has_audio_stream(in_video)
    cmd = ["ffmpeg", "-y", "-i", in_video]
    if not need_audio:
        cmd.extend(["-f", "lavfi", "-t", "0.1", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
    fc_chains = [f"[0:v]{base},format=rgba[v0]"]
    next_input_file_idx = 2 if not need_audio else 1
    current_v_label = "[v0]"

    if apply_folder_overlay and folder_overlay_png and Path(folder_overlay_png).exists():
        cmd.extend(["-loop", "1", "-i", folder_overlay_png])
        tint_chains = overlay_tint_chains(f"{next_input_file_idx}:v", "ov_folder", target_w, target_h, overlay_tint_rgb, overlay_tint_strength, "t1_")
        fc_chains.extend(tint_chains)
        next_v_label = f"[v{next_input_file_idx}]"
        fc_chains.append(f"{current_v_label}[ov_folder]overlay=0:0:format=auto,format=rgba{next_v_label}")
        current_v_label = next_v_label
        next_input_file_idx += 1

    if banner_png and Path(banner_png).exists():
        cmd.extend(["-loop", "1", "-i", banner_png])
        banner_chain = f"[{next_input_file_idx}:v]scale={target_w}:{target_h},format=rgba"
        if MAKE_BLACK_TRANSPARENT:
            banner_chain += f",colorkey=0x000000:{BLACK_KEY_SIMILARITY}:{BLACK_KEY_BLEND}"
        fc_chains.append(f"{banner_chain}[ov_banner]")
        next_v_label = "[v_final_banner]"
        fc_chains.append(f"{current_v_label}[ov_banner]overlay=0:0:format=auto:enable='gte(t,{banner_delay})',format=yuv420p{next_v_label}")
        current_v_label = next_v_label
        next_input_file_idx += 1
    else:
        fc_chains.append(f"{current_v_label}setsar=1,format=yuv420p[v_final_out]")
        current_v_label = "[v_final_out]"

    if need_audio:
        if abs(speed - 1.0) > 1e-6:
            fc_chains.append(f"[0:a]atempo={speed},aformat=sample_rates=48000:channel_layouts=stereo[a_out]")
        else:
            fc_chains.append(f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a_out]")
        audio_map = "[a_out]"
    else:
        fc_chains.append(f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a_out]")
        audio_map = "[a_out]"

    fc = ";".join(fc_chains)
    # ✅ [FIX] -bf 0 추가하여 B-frame 비활성화 → 첫 프레임 검은 화면 해결
    cmd.extend(["-filter_complex", fc, "-map", current_v_label, "-map", audio_map, "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-bf", "0", "-g", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out_video])
    run(cmd)


# ✅ [NEW] 첫 번째 비디오 클립을 인트로로 사용 (정지 이미지 방식 폐기)
def make_intro_from_video(first_video: str, intro_audio: str, out_video: str, target_w: int, target_h: int, fps: float, scale_mode: str, look_filter: Optional[str], folder_overlay_png: Optional[str], overlay_tint_rgb: Optional[Tuple[float, float, float]], overlay_tint_strength: float, zoom: float, speed: float) -> None:
    """첫 번째 비디오 클립에 인트로 오디오를 덮어씌워 인트로 생성"""
    intro_duration = get_media_duration_seconds(intro_audio)
    if intro_duration <= 0.05:
        intro_duration = 3.0
    
    base = build_base_chain(target_w, target_h, fps, scale_mode, look_filter, zoom, speed)
    
    # ✅ [FIX] -ss 0.1로 첫 0.1초 건너뛰기 (검은 화면 방지)
    cmd = ["ffmpeg", "-y", "-ss", "0.1", "-t", str(intro_duration), "-i", first_video, "-i", intro_audio]
    
    fc_chains = [f"[0:v]{base},format=rgba[v0]"]
    input_idx = 2
    current_v_label = "[v0]"

    if folder_overlay_png and Path(folder_overlay_png).exists():
        cmd.extend(["-loop", "1", "-i", folder_overlay_png])
        tint_chains = overlay_tint_chains(f"{input_idx}:v", "ov_folder", target_w, target_h, overlay_tint_rgb, overlay_tint_strength, "t2_")
        fc_chains.extend(tint_chains)
        next_v_label = f"[v{input_idx}]"
        fc_chains.append(f"{current_v_label}[ov_folder]overlay=0:0:format=auto,format=rgba{next_v_label}")
        current_v_label = next_v_label
        input_idx += 1

    fc_chains.append(f"{current_v_label}setsar=1,format=yuv420p[v_final_out]")
    current_v_label = "[v_final_out]"

    # 인트로 오디오 사용 (원본 비디오 오디오 무시)
    audio_chain = "[1:a]"
    if abs(speed - 1.0) > 1e-6:
        audio_chain += f"atempo={speed},"
    audio_chain += "aformat=sample_rates=48000:channel_layouts=stereo[a_out]"
    fc_chains.append(audio_chain)
    
    fc = ";".join(fc_chains)
    # ✅ [FIX] -bf 0 추가하여 B-frame 비활성화
    cmd.extend(["-filter_complex", fc, "-map", current_v_label, "-map", "[a_out]", "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-bf", "0", "-g", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out_video])
    run(cmd)


def make_static_segment(image_path: str, audio_path: str, out_video: str, target_w: int, target_h: int, fps: float, scale_mode: str, look_filter: Optional[str]) -> None:
    base = build_base_chain(target_w, target_h, fps, scale_mode, look_filter, 1.0, 1.0)
    # ✅ [FIX] -bf 0 추가하여 B-frame 비활성화
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", image_path, "-i", audio_path, "-filter_complex", f"[0:v]{base},setsar=1,format=yuv420p[v];[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a]", "-map", "[v]", "-map", "[a]", "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-bf", "0", "-g", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out_video]
    run(cmd)


def concat_segments(file_list: List[str], output_path: str) -> None:
    cmd = ["ffmpeg", "-y"]
    for p in file_list:
        cmd.extend(["-i", str(Path(p).resolve())])

    n = len(file_list)
    filter_inputs = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    fc = f"{filter_inputs}concat=n={n}:v=1:a=1[v][a]"

    cmd.extend([
        "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-bf", "0", "-g", "30",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ])
    run(cmd)


def process_one_folder(folder: Path, output_path_tiktok: Path, output_path_prod: Path, intro_audio: Path, outro: Path, seed: int, max_videos: Optional[int], tmp_root: Path, keep_tmp: bool, target_w: int, target_h: int, scale_mode: str, look_filter: Optional[str], force_fps: Optional[float], overlay_tint_rgb: Optional[Tuple[float, float, float]], overlay_tint_strength: float, zoom: float, speed: float) -> bool:
    vids = list_files(folder, VIDEO_EXTS)
    if not vids:
        print("⏭️  Skip (no videos):", folder)
        return False

    overlay_path = folder / "overlay.png"
    folder_overlay_png = str(overlay_path.resolve()) if overlay_path.exists() else None
    banner_png = str(BANNER_PATH.resolve()) if BANNER_PATH.exists() else None

    if folder_overlay_png is None:
        print("⚠️  overlay.png not found in folder -> folder overlay disabled")

    random.shuffle(vids)
    if max_videos is not None and max_videos > 0:
        vids = vids[:max_videos]

    print("\n📁 Folder:", folder.name)
    print("Clips:", len(vids))

    tmpdir = tmp_root / safe_stem(folder.name)
    if tmpdir.exists():
        shutil.rmtree(tmpdir, ignore_errors=True)
    tmpdir.mkdir(parents=True, exist_ok=True)

    first_video = str(vids[0])
    _, _, detected_fps = get_video_props(first_video)
    fps = float(force_fps) if force_fps is not None else float(detected_fps)

    # ✅ [NEW] 첫 번째 비디오 클립을 인트로로 사용 (정지 이미지 방식 폐기)
    intro_norm_tiktok = str((tmpdir / "norm_00_intro_tk.mp4").resolve())
    make_intro_from_video(first_video, str(intro_audio), intro_norm_tiktok, target_w, target_h, fps, scale_mode, look_filter, folder_overlay_png, overlay_tint_rgb, overlay_tint_strength, zoom, speed)

    normalized_body_tiktok: List[str] = []
    normalized_body_prod: List[str] = []

    for idx, vp in enumerate(vids, start=1):
        current_banner_tk = None if idx == 1 else banner_png
        outp_tk = str((tmpdir / f"norm_{idx:02d}_in_tk.mp4").resolve())
        transcode_with_optional_overlay(str(vp), outp_tk, target_w, target_h, fps, scale_mode, look_filter, folder_overlay_png, True, overlay_tint_rgb, overlay_tint_strength, current_banner_tk, 0.0, zoom, speed)
        normalized_body_tiktok.append(outp_tk)

        outp_pd = str((tmpdir / f"norm_{idx:02d}_in_pd.mp4").resolve())
        transcode_with_optional_overlay(str(vp), outp_pd, target_w, target_h, fps, scale_mode, look_filter, folder_overlay_png, True, overlay_tint_rgb, overlay_tint_strength, None, 0.0, zoom, speed)
        normalized_body_prod.append(outp_pd)

    pre_outro_seg = []
    if normalized_body_tiktok and PRE_OUTRO_AUDIO_PATH.exists():
        last_clip_path = normalized_body_tiktok[-1]
        last_frame_path = str((tmpdir / "last_frame_for_cta.png").resolve())
        extract_last_frame(last_clip_path, last_frame_path)
        if Path(last_frame_path).exists():
            pre_outro_video = str((tmpdir / "norm_99_pre_outro.mp4").resolve())
            make_static_segment(last_frame_path, str(PRE_OUTRO_AUDIO_PATH), pre_outro_video, target_w, target_h, fps, scale_mode, None)
            pre_outro_seg = [pre_outro_video]
        else:
            print("⚠️ Last frame extraction failed -> skipping CTA segment")

    outro_norm = str((tmpdir / f"norm_{len(vids)+1:02d}_outro.mp4").resolve())
    transcode_with_optional_overlay(str(outro), outro_norm, target_w, target_h, fps, scale_mode, None, None, False, None, 0.0, None, 0.0, 1.0, 1.0)

    output_path_tiktok.parent.mkdir(parents=True, exist_ok=True)
    list_tiktok = [intro_norm_tiktok] + normalized_body_tiktok + pre_outro_seg + [outro_norm]
    concat_segments(list_tiktok, str(output_path_tiktok))
    print("✅ Done (TikTok):", output_path_tiktok.name)

    output_path_prod.parent.mkdir(parents=True, exist_ok=True)
    list_prod = normalized_body_prod + pre_outro_seg + [outro_norm]
    concat_segments(list_prod, str(output_path_prod))
    print("✅ Done (Production):", output_path_prod.name)

    if not keep_tmp:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


def main() -> None:
    check_ffmpeg()
    if not ROOT_DIR.exists() or not ROOT_DIR.is_dir():
        die(f"Folder not found: {ROOT_DIR.resolve()}")
    if not OUTRO_VIDEO.exists():
        die(f"Outro video not found: {OUTRO_VIDEO.resolve()}")
    if not INTRO_AUDIO_FALLBACK.exists():
        if not (INTRO_AUDIO_DIR.exists() and INTRO_AUDIO_DIR.is_dir() and list_files(INTRO_AUDIO_DIR, AUDIO_EXTS)):
            die(f"Intro audio not found: {INTRO_AUDIO_FALLBACK.resolve()}")
    if not BANNER_PATH.exists():
        print(f"⚠️ Warning: Banner image not found.")
    if not PRE_OUTRO_AUDIO_PATH.exists():
        print(f"⚠️ Warning: Pre-Outro audio not found.")

    prod_dir = OUTPUT_DIR / "production"
    tk_dir = OUTPUT_DIR / "tiktok"
    prod_dir.mkdir(parents=True, exist_ok=True)
    tk_dir.mkdir(parents=True, exist_ok=True)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)

    state = load_state(STATE_FILE)
    cycle = int(state["cycle"])
    done_names = set(state["done"])

    all_subfolders = sorted([p for p in ROOT_DIR.iterdir() if p.is_dir()], key=natural_sort_key)
    eligible_folders = [sf for sf in all_subfolders if folder_has_any_video(sf)]
    if not eligible_folders:
        die(f"No eligible folders under: {ROOT_DIR.resolve()}")

    eligible_names = set(sf.name for sf in eligible_folders)
    done_names = set(n for n in done_names if n in eligible_names)
    if done_names == eligible_names:
        done_names = set()
        cycle += 1

    remaining = [sf for sf in eligible_folders if sf.name not in done_names]
    k = min(PICK_FOLDERS_PER_RUN, len(remaining))
    picked = remaining[:k]

    look_name, look_filter = cycle_look(cycle)
    chosen_intro = pick_intro_audio(INTRO_AUDIO_FALLBACK, INTRO_AUDIO_DIR, cycle)
    tint_hex = pick_palette_color_hex(OVERLAY_TINT_PALETTE, cycle)
    tint_rgb = parse_hex_color(tint_hex) if tint_hex else None
    tint_strength = max(0.0, min(1.0, float(OVERLAY_TINT_STRENGTH)))
    force_fps = float(FORCE_FPS) if FORCE_FPS and FORCE_FPS > 0 else None
    zoom, speed, preset_name = get_zoom_speed_auto(cycle)

    print("\n=== Run Info ===")
    print("Cycle:", cycle, "| Look:", look_name, "| Preset:", preset_name)
    print("================\n")

    processed_names: List[str] = []
    for idx, sf in enumerate(picked, start=1):
        out_path_tiktok = tk_dir / f"v{idx}_tiktok.mp4"
        out_path_prod = prod_dir / f"v{idx}_production.mp4"
        ok = process_one_folder(sf, out_path_tiktok, out_path_prod, chosen_intro, OUTRO_VIDEO, BASE_SEED, MAX_VIDEOS_PER_FOLDER, TMP_ROOT, KEEP_TMP, TARGET_W, TARGET_H, SCALE_MODE, look_filter, force_fps, tint_rgb, tint_strength, zoom, speed)
        if ok:
            processed_names.append(sf.name)

    done_names.update(processed_names)
    if done_names == eligible_names:
        save_state(STATE_FILE, {"cycle": cycle + 1, "done": []})
        print(f"\n✅ Cycle complete -> next cycle: {cycle + 1}")
    else:
        save_state(STATE_FILE, {"cycle": cycle, "done": sorted(done_names)})
        print(f"\n✅ State saved. Remaining: {len(eligible_names) - len(done_names)}")


if __name__ == "__main__":
    main()