"""
세로형(1080x1920) 정적 인트로 카드 렌더러.
Download.mp4의 인트로 카드 스타일을 재현.
long-form-video/frame_renderer.py를 세로 비율에 맞게 수정.
"""
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).parent
FONT_BOLD = str(BASE_DIR / "fonts" / "maruburi" / "TTF" / "MaruBuri-Bold.ttf")
FONT_REGULAR = str(BASE_DIR / "fonts" / "maruburi" / "TTF" / "MaruBuri-Regular.ttf")
FLAG_PATH = str(BASE_DIR / "assets" / "flag.png")
LOGO_PATH = str(BASE_DIR / "assets" / "koko_logo.png")


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _draw_centered_text(draw, text, font, fill, y, width):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, font=font, fill=fill)


def _fit_text(draw, text, font_path, max_size, max_width):
    size = max_size
    font = ImageFont.truetype(font_path, size)
    bbox = draw.textbbox((0, 0), text, font=font)
    while bbox[2] - bbox[0] > max_width and size > 20:
        size -= 2
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
    return font


def _radial_gradient(w, h, center_color, edge_color):
    cx, cy = w // 2, h // 2
    max_dist = math.sqrt(cx * cx + cy * cy)
    ys, xs = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    frac = np.clip(dist / max_dist, 0.0, 1.0)
    blend = np.where(frac > 0.6, ((frac - 0.6) / 0.4) ** 2, 0.0)
    center = np.array(center_color, dtype=np.float32)
    edge = np.array(edge_color, dtype=np.float32)
    arr = np.full((h, w, 3), center, dtype=np.float32)
    arr += blend[..., np.newaxis] * (edge - center)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def render_intro_card(
    korean_text: str,
    romanization: str,
    english_text: str,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    bg_hex: str = "#FFD8DC",  # Download.mp4 분홍 톤
    edge_hex: str = "#F5B5BA",
):
    """Download.mp4 인트로 카드 스타일의 세로 PNG를 생성."""
    img = _radial_gradient(width, height, _hex_to_rgb(bg_hex), _hex_to_rgb(edge_hex))
    draw = ImageDraw.Draw(img)
    center_x = width // 2
    max_text_w = width - 120

    # 1) 상단 헤더 "Search 'koko'"
    header_font = ImageFont.truetype(FONT_BOLD, 48)
    _draw_centered_text(draw, "Search  koko", header_font, (40, 40, 40),
                        int(height * 0.10), width)

    # 2) 한국 국기 (가운데 상단)
    if os.path.exists(FLAG_PATH):
        flag = Image.open(FLAG_PATH).convert("RGBA")
        target_w = 280
        ratio = target_w / flag.width
        flag = flag.resize((target_w, int(flag.height * ratio)), Image.LANCZOS)
        fx = center_x - flag.width // 2
        fy = int(height * 0.15)
        img.paste(flag, (fx, fy), flag)
        draw = ImageDraw.Draw(img)

    # 3) "Native Phrase" 라벨
    label_font = ImageFont.truetype(FONT_BOLD, 56)
    _draw_centered_text(draw, "Native Phrase", label_font, (30, 30, 30),
                        int(height * 0.32), width)

    # 4) 영어 번역
    en_y = int(height * 0.42)
    en_font = _fit_text(draw, english_text, FONT_REGULAR, 56, max_text_w)
    _draw_centered_text(draw, english_text, en_font, (50, 50, 50), en_y, width)

    # 5) 한글 표현 (큰 bold)
    kr_y = int(height * 0.50)
    kr_font = _fit_text(draw, korean_text, FONT_BOLD, 160, max_text_w)
    _draw_centered_text(draw, korean_text, kr_font, (20, 20, 20), kr_y, width)

    # 6) 로마자 표기 (italic 느낌으로 회색)
    rom_y = int(height * 0.62)
    rom_text = romanization
    rom_font = _fit_text(draw, rom_text, FONT_REGULAR, 52, max_text_w)
    _draw_centered_text(draw, rom_text, rom_font, (130, 130, 130), rom_y, width)

    # 7) 하단 koko 로고
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        target_w = 520
        ratio = target_w / logo.width
        logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
        # 둥근 모서리
        radius = 24
        mask = Image.new("L", (logo.width, logo.height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, logo.width, logo.height], radius=radius, fill=255
        )
        logo.putalpha(mask)
        lx = center_x - logo.width // 2
        ly = int(height * 0.78)
        img.paste(logo, (lx, ly), logo)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


if __name__ == "__main__":
    out = render_intro_card(
        korean_text="이리 와",
        romanization="iri wa",
        english_text="Come here",
        output_path=str(BASE_DIR / "test_output" / "intro_card_test.png"),
    )
    print(f"OK: {out}")
