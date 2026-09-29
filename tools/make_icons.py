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

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "static", "icons")
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
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), NAVY)
    d = ImageDraw.Draw(img)

    # 아래쪽 파란 띠. 32px 에서 글자만 남으면 무엇인지 알 수 없어서, 멀리서도
    # 구분되는 형태를 하나 둡니다.
    bar = max(2, int(size * 0.10))
    d.rectangle([0, size - bar, size, size], fill=BLUE)

    text = "MP"
    f = _font(int(size * 0.46))
    box = d.textbbox((0, 0), text, font=f)
    d.text(((size - (box[2] - box[0])) / 2 - box[0],
            (size - bar - (box[3] - box[1])) / 2 - box[1]),
           text, font=f, fill=WHITE)
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
