"""
테스트용: 단일 폴더(103이리 와)를 새 인트로 카드 방식으로 전체 파이프라인 처리.
shuffle_merge.py의 함수를 재사용하고 인트로 생성 부분만 교체.
"""
import shutil
import subprocess
from pathlib import Path

import shuffle_merge as sm
from intro_card_renderer import render_intro_card

BASE = Path(__file__).parent
TARGET_FOLDER = BASE / "dramas" / "43사랑해"
OUT_DIR = BASE / "test_output"
TMP_DIR = BASE / ".tmp_test_saranghae"

EXPRESSION = {
    "korean": "사랑해",
    "romanization": "saranghae",
    "english": "I love you",
}


def make_intro_from_card(card_png: str, intro_audio: str, out_video: str,
                          target_w: int, target_h: int, fps: float,
                          duration: float):
    """정적 카드 PNG + 인트로 오디오 → 영상 생성."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{duration}", "-i", card_png,
        "-i", intro_audio,
        "-vf", f"scale={target_w}:{target_h},setsar=1,fps={fps},format=yuv420p",
        "-af", "aformat=sample_rates=48000:channel_layouts=stereo",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-bf", "0", "-g", "30",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart",
        out_video,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    sm.check_ffmpeg()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    target_w, target_h = sm.TARGET_W, sm.TARGET_H
    fps = sm.FORCE_FPS
    cycle = 1
    look_name, look_filter = sm.cycle_look(cycle)
    zoom, speed, _ = sm.get_zoom_speed_auto(cycle)
    tint_hex = sm.pick_palette_color_hex(sm.OVERLAY_TINT_PALETTE, cycle)
    tint_rgb = sm.parse_hex_color(tint_hex)
    tint_strength = sm.OVERLAY_TINT_STRENGTH

    # 1) 인트로 카드 PNG 생성
    card_png = str(OUT_DIR / "intro_card.png")
    render_intro_card(
        korean_text=EXPRESSION["korean"],
        romanization=EXPRESSION["romanization"],
        english_text=EXPRESSION["english"],
        output_path=card_png,
        width=target_w, height=target_h,
    )

    # 2) 인트로 오디오 길이 확인 → 카드 영상 길이 결정
    intro_audio = str(sm.INTRO_AUDIO_FALLBACK)
    if not Path(intro_audio).exists():
        intro_audio = str(sm.pick_intro_audio(
            sm.INTRO_AUDIO_FALLBACK, sm.INTRO_AUDIO_DIR, cycle))
    intro_dur = sm.get_media_duration_seconds(intro_audio)
    if intro_dur < 1.0:
        intro_dur = 1.7  # 최소 보장
    print(f"[1/5] Intro audio: {intro_dur:.2f}s")

    intro_clip = str(TMP_DIR / "intro_card.mp4")
    make_intro_from_card(card_png, intro_audio, intro_clip,
                          target_w, target_h, fps, intro_dur)
    print(f"[2/5] Intro card video built: {intro_clip}")

    # 3) 드라마 클립 선택 (15초 채울 때까지)
    vids = sm.list_files(TARGET_FOLDER, sm.VIDEO_EXTS)
    selected = []
    total_dur = intro_dur  # 인트로도 포함하여 15초 검증
    for vp in vids:
        selected.append(vp)
        try:
            d = sm.get_media_duration_seconds(str(vp))
            total_dur += d / speed
        except Exception:
            total_dur += 4.0
        if total_dur >= sm.MIN_TOTAL_DURATION:
            break
    print(f"[3/5] Selected {len(selected)} clips, expected total ~{total_dur:.1f}s")

    # 4) 드라마 클립 정규화 (overlay.png + banner 적용)
    overlay_path = TARGET_FOLDER / "overlay.png"
    folder_overlay = str(overlay_path.resolve()) if overlay_path.exists() else None
    banner_png = str(sm.BANNER_PATH.resolve()) if sm.BANNER_PATH.exists() else None

    body_clips = []
    for idx, vp in enumerate(selected, start=1):
        out = str(TMP_DIR / f"norm_{idx:02d}.mp4")
        sm.transcode_with_optional_overlay(
            in_video=str(vp), out_video=out,
            target_w=target_w, target_h=target_h, fps=fps,
            scale_mode=sm.SCALE_MODE, look_filter=look_filter,
            folder_overlay_png=folder_overlay, apply_folder_overlay=True,
            overlay_tint_rgb=tint_rgb, overlay_tint_strength=tint_strength,
            banner_png=banner_png, banner_delay=0.0,
            zoom=zoom, speed=speed,
        )
        body_clips.append(out)
    print(f"[4/5] Normalized {len(body_clips)} drama clips")

    # 5) 인트로 카드 + 드라마 클립 → CTA + 아웃트로 오버레이
    all_clips = [intro_clip] + body_clips
    cta_audio = str(sm.PRE_OUTRO_AUDIO_PATH) if sm.PRE_OUTRO_AUDIO_PATH.exists() else None
    final_path = str(OUT_DIR / "test_saranghae_full.mp4")
    sm.concat_with_outro_overlay(
        file_list=all_clips, outro_path=str(sm.OUTRO_VIDEO),
        output_path=final_path,
        target_w=target_w, target_h=target_h, fps=fps,
        cta_audio_path=cta_audio,
    )

    # 검증
    final_dur = sm.get_media_duration_seconds(final_path)
    print(f"\n[5/5] DONE: {final_path}")
    print(f"      Duration: {final_dur:.2f}s  ({'PASS' if final_dur >= 15 else 'FAIL'} >= 15s)")


if __name__ == "__main__":
    main()
