"""
Download.mp4 스타일 영상 생성기.

구조:
  ① 인트로 카드 (정적 PNG + 한국어 TTS = 표현 발음)
  ② 드라마 클립 1개 (자막 오버레이 + 배너)
  ③ 풀스크린 아웃트로

CTA 오디오, 작은 코너 아웃트로 오버레이는 사용하지 않음.
"""
import asyncio
import shutil
import subprocess
from pathlib import Path

import edge_tts

import shuffle_merge as sm
from intro_card_renderer import render_intro_card

BASE = Path(__file__).parent
OUT_DIR = BASE / "test_output"
TMP_DIR = BASE / ".tmp_test_annyeong"

TARGET_FOLDER = BASE / "dramas" / "149안녕"
EXPRESSION = {
    "korean": "안녕",
    "romanization": "annyeong",
    "english": "Hello (casual)",
}

# 한국어 자연스러운 여성 음성
EDGE_VOICE_KR = "ko-KR-SunHiNeural"
INTRO_HOLD_AFTER_TTS = 0.4   # 인트로 카드: TTS 끝나고 추가로 보여주는 시간
POST_DRAMA_PAUSE_BEFORE_CTA = 0.5   # 드라마 끝나고 CTA 오디오 재생 전 정적
POST_DRAMA_PAUSE_AFTER_CTA = 0.3    # CTA 끝나고 아웃트로 전 정적
POST_DRAMA_FADE_DUR = 0.3            # 드라마 freeze 후 어두워지는 시간 (초)
POST_DRAMA_DARKEN_ALPHA = 0.4        # 검은 오버레이 최종 불투명도 (0~1)
MIN_TOTAL_SEC = 15.0   # 최소 총 영상 길이


async def _gen_tts_async(text: str, out_path: str, voice: str) -> str:
    for attempt in range(5):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(out_path)
            return out_path
        except Exception as e:
            if attempt < 4:
                await asyncio.sleep(2 ** attempt)
            else:
                raise


def gen_korean_tts(text: str, out_path: str) -> str:
    asyncio.run(_gen_tts_async(text, out_path, EDGE_VOICE_KR))
    return out_path


def make_intro_clip_with_tts(card_png: str, tts_audio: str, out_video: str,
                              target_w: int, target_h: int, fps: float):
    """카드 PNG + TTS 오디오 → 영상. TTS 재생 + INTRO_HOLD_AFTER_TTS 추가 hold."""
    tts_dur = sm.get_media_duration_seconds(tts_audio)
    duration = tts_dur + INTRO_HOLD_AFTER_TTS
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{duration}", "-i", card_png,
        "-i", tts_audio,
        "-vf", f"scale={target_w}:{target_h},setsar=1,fps={fps},format=yuv420p",
        "-af", f"apad=pad_dur={INTRO_HOLD_AFTER_TTS},"
               f"aformat=sample_rates=48000:channel_layouts=stereo",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-bf", "0", "-g", "30",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart",
        out_video,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return duration


def extract_last_frame(in_video: str, out_png: str):
    """영상의 마지막 프레임을 PNG로 추출."""
    cmd = ["ffmpeg", "-y", "-sseof", "-0.1", "-i", in_video,
           "-vsync", "vfr", "-q:v", "2", "-update", "1", "-vframes", "1", out_png]
    subprocess.run(cmd, check=True, capture_output=True)


def make_post_drama_segment(last_frame_png: str, cta_audio: str,
                              out_video: str, target_w: int, target_h: int,
                              fps: float, total_duration: float):
    """드라마 마지막 프레임을 freeze + 어두워지는 페이드 효과.
       타임라인:
         [0 ~ pause_before]            정적, 화면 점진적으로 어두워짐
         [pause_before ~ +cta_dur]     CTA 오디오 재생 (이미 어두워진 상태)
         [cta 끝 ~ total_duration]     정적
       시각 효과:
         [0 ~ FADE_DUR] 검은 오버레이 alpha 0 → DARKEN_ALPHA 페이드 인
         [FADE_DUR ~ 끝] 검은 오버레이 alpha 고정
    """
    delay_ms = int(POST_DRAMA_PAUSE_BEFORE_CTA * 1000)

    filter_complex = (
        f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=disable,"
        f"setsar=1,fps={fps}[base];"
        f"color=c=black:s={target_w}x{target_h}:d={total_duration}:r={fps},"
        f"format=yuva420p,fade=t=in:st=0:d={POST_DRAMA_FADE_DUR}:alpha=1,"
        f"colorchannelmixer=aa={POST_DRAMA_DARKEN_ALPHA}[shade];"
        f"[base][shade]overlay=0:0,format=yuv420p[v];"
        f"[1:a]adelay={delay_ms}|{delay_ms},apad,"
        f"aformat=sample_rates=48000:channel_layouts=stereo[a]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{total_duration}", "-i", last_frame_png,
        "-i", cta_audio,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", f"{total_duration}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-bf", "0", "-g", "30",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        out_video,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return total_duration


def normalize_outro(outro_in: str, outro_out: str,
                    target_w: int, target_h: int, fps: float):
    """아웃트로를 타겟 해상도/포맷으로 정규화 (오버레이가 아닌 풀스크린)."""
    cmd = [
        "ffmpeg", "-y", "-i", outro_in,
        "-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
               f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
               f"fps={fps},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-bf", "0", "-g", "30",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        outro_out,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def pick_longest_clip(folder: Path):
    """폴더에서 가장 긴 클립 1개만 선택."""
    vids = sm.list_files(folder, sm.VIDEO_EXTS)
    if not vids:
        return None
    return max(vids, key=lambda v: sm.get_media_duration_seconds(str(v)))


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

    # 1) TTS 생성
    tts_path = str(TMP_DIR / "phrase_tts.mp3")
    gen_korean_tts(EXPRESSION["korean"], tts_path)
    tts_dur = sm.get_media_duration_seconds(tts_path)
    print(f"[1/7] Phrase TTS: '{EXPRESSION['korean']}' = {tts_dur:.2f}s")

    # 2) 인트로 카드 + TTS (짧게)
    card_png = str(TMP_DIR / "intro_card.png")
    render_intro_card(
        korean_text=EXPRESSION["korean"],
        romanization=EXPRESSION["romanization"],
        english_text=EXPRESSION["english"],
        output_path=card_png, width=target_w, height=target_h,
    )
    intro_clip = str(TMP_DIR / "intro.mp4")
    intro_dur = make_intro_clip_with_tts(card_png, tts_path, intro_clip,
                                          target_w, target_h, fps)
    print(f"[2/7] Intro clip built: {intro_dur:.2f}s")

    # 3) 드라마 클립 1개 선택 + 정규화
    chosen = pick_longest_clip(TARGET_FOLDER)
    if chosen is None:
        raise RuntimeError(f"No videos in {TARGET_FOLDER}")
    print(f"[3/7] Selected drama clip: {chosen.name}")

    overlay_path = TARGET_FOLDER / "overlay.png"
    folder_overlay = str(overlay_path.resolve()) if overlay_path.exists() else None
    banner_png = str(sm.BANNER_PATH.resolve()) if sm.BANNER_PATH.exists() else None

    drama_norm = str(TMP_DIR / "drama.mp4")
    sm.transcode_with_optional_overlay(
        in_video=str(chosen), out_video=drama_norm,
        target_w=target_w, target_h=target_h, fps=fps,
        scale_mode=sm.SCALE_MODE, look_filter=look_filter,
        folder_overlay_png=folder_overlay, apply_folder_overlay=True,
        overlay_tint_rgb=tint_rgb, overlay_tint_strength=tint_strength,
        banner_png=banner_png, banner_delay=0.0,
        zoom=zoom, speed=speed,
    )
    drama_dur = sm.get_media_duration_seconds(drama_norm)
    print(f"[3/7] Drama clip normalized: {drama_dur:.2f}s")

    # 4) 아웃트로 풀스크린 정규화
    outro_norm = str(TMP_DIR / "outro.mp4")
    normalize_outro(str(sm.OUTRO_VIDEO), outro_norm, target_w, target_h, fps)
    outro_dur = sm.get_media_duration_seconds(outro_norm)
    print(f"[4/7] Outro normalized: {outro_dur:.2f}s")

    # 5) CTA 오디오 길이 확인 + post-drama 세그먼트 길이 계산
    cta_path = str(sm.PRE_OUTRO_AUDIO_PATH)
    if not Path(cta_path).exists():
        raise RuntimeError(f"CTA audio not found: {cta_path}")
    cta_dur = sm.get_media_duration_seconds(cta_path)
    min_post_dur = (POST_DRAMA_PAUSE_BEFORE_CTA + cta_dur + POST_DRAMA_PAUSE_AFTER_CTA)
    needed_post = max(min_post_dur,
                       MIN_TOTAL_SEC - intro_dur - drama_dur - outro_dur)
    print(f"[5/7] Post-drama target: {needed_post:.2f}s "
          f"(pause {POST_DRAMA_PAUSE_BEFORE_CTA}s + CTA {cta_dur:.2f}s "
          f"+ extra {needed_post - POST_DRAMA_PAUSE_BEFORE_CTA - cta_dur:.2f}s)")

    # 6) 드라마 마지막 프레임 추출 → freeze + CTA 세그먼트 생성
    last_frame = str(TMP_DIR / "drama_last.png")
    extract_last_frame(drama_norm, last_frame)
    post_clip = str(TMP_DIR / "post_drama.mp4")
    post_dur = make_post_drama_segment(last_frame, cta_path, post_clip,
                                        target_w, target_h, fps, needed_post)
    print(f"[6/7] Post-drama clip built: {post_dur:.2f}s")

    # 7) concat: 인트로 + 드라마 + 정적+TTS + 아웃트로
    final_path = str(OUT_DIR / "test_annyeong.mp4")
    sm.concat_segments([intro_clip, drama_norm, post_clip, outro_norm], final_path)

    final_dur = sm.get_media_duration_seconds(final_path)
    status = "PASS" if final_dur >= MIN_TOTAL_SEC else "FAIL"
    print(f"\n[7/7] DONE: {final_path}")
    print(f"      Total: {final_dur:.2f}s = intro {intro_dur:.2f}"
          f" + drama {drama_dur:.2f} + post {post_dur:.2f}"
          f" + outro {outro_dur:.2f}  [{status}]")


if __name__ == "__main__":
    main()
