# -*- coding: utf-8 -*-
"""
홈 화면 아이콘을 만든다.

체크인된 PNG 를 손으로 고치는 대신 여기서 생성합니다 - 색을 바꾸고 싶으면 이
파일의 값을 고치고 다시 돌리면 되고, 어떤 크기가 왜 필요한지도 한곳에 적힙니다.

    python tools/make_icons.py

  180  iOS 홈 화면 (apple-touch-icon). iOS 는 manifest 의 icons 를 보지 않습니다.
  192  안드로이드 홈 화면
  512  스플래시와 앱 목록
   32  브라우저 탭
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "icons")
NAVY = (11, 31, 63)          # m.css 의 탭 바 색
BLUE = (37, 99, 235)
WHITE = (255, 255, 255)
SIZES = {"icon-32.png": 32, "icon-180.png": 180, "icon-192.png": 192,
         "icon-512.png": 512}

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\seguibl.ttf",      # Segoe UI Black
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(px):
    from PIL import ImageFont
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def draw(size):
    """
    로고를 남색 바탕에 올립니다.

    예전에는 "MP" 를 그렸습니다. 32px 에서도 읽히긴 했지만 어느 은행의
    도구인지는 말해 주지 않았습니다. 동근 마크는 작게 줄여도 형태가
    남습니다. 로고 파일은 바깥이 투명해서 바탕색이 그대로 비칩니다.
    """
    from PIL import Image

    img = Image.new("RGB", (size, size), NAVY)
    logo_path = os.path.join(ROOT, "static", "logo.png")
    if not os.path.exists(logo_path):
        # 로고가 없으면 아래 띄라도 남깁니다 - 빈 네모를 내보내는 것보다 낫습니다.
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        bar = max(2, int(size * 0.10))
        d.rectangle([0, size - bar, size, size], fill=BLUE)
        return img

    logo = Image.open(logo_path).convert("RGBA")
    inner = max(1, int(size * 0.76))        # 가장자리 여백
    logo = logo.resize((inner, inner), Image.LANCZOS)
    off = (size - inner) // 2
    img.paste(logo, (off, off), logo)
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, size in SIZES.items():
        path = os.path.join(OUT, name)
        draw(size).save(path, format="PNG", optimize=True)
        print(f"  {name:<16} {size}x{size}  {os.path.getsize(path)/1024:.1f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
