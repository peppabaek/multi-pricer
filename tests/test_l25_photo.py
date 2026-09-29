# -*- coding: utf-8 -*-
"""
L25 폰으로 찍은 사진.

요구사항은 단순합니다. 트레이더가 term sheet 을 찍어 갤러리에 저장하고, 그 사진을
올리면, AI 가 읽어서 거래조건을 뽑고, 그걸로 프라이싱한다.

그 경로는 이미 있었지만, 실제 폰 사진은 테스트가 쓰던 화면 캡처 PNG 와 세 군데가
다릅니다.

  HEIC   아이폰 기본 포맷. 매직 바이트 목록에도 확장자 표에도 없어서 "이미지"로
         분류되지 않았습니다. 텍스트로 넘어가 latin-1 로 깨져 읽히고, 결국
         "읽을 수 있는 내용을 찾지 못했습니다" 라는 원인과 무관한 말이 나왔습니다.
  회전   세로로 찍은 사진은 픽셀이 가로로 저장되고 EXIF 표시만 붙습니다. 원본을
         그대로 보내면 모델은 누운 표를 봅니다.
  크기   4032x3024, 3~12MB. 프로바이더 이미지 한도에 걸립니다.

여기서는 모델을 부르지 않습니다. 모델에 "무엇이" 전달되는지만 봅니다.
"""
import io
import os
import sys

from harness import case, run_all

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sample_formats as S
from server.termsheet import (sniff_kind, prepare_photo, process_termsheet,
                              _PHOTO_MAX_EDGE, _PHOTO_MAX_BYTES)
from test_l11_scenarios import _stub


def _has_heif():
    try:
        import pillow_heif       # noqa: F401
        return True
    except ImportError:
        return False


@case("L25-1", "폰 사진(JPEG)을 이미지로 알아본다")
def t_1():
    raw = S.phone_jpeg_bytes()
    if sniff_kind(raw, "IMG_4821.JPG") != "image":
        raise AssertionError("폰 JPEG 을 이미지로 분류하지 못함")


@case("L25-2", "아이폰 HEIC 를 이미지로 알아본다")
def t_2():
    if not _has_heif():
        raise AssertionError("pillow-heif 미설치 - HEIC 를 지원한다고 말할 수 없음")
    raw = S.heic_bytes()
    # 확장자를 빼고도 알아봐야 합니다. 공유로 받은 파일은 이름이 제각각입니다.
    if sniff_kind(raw, "") != "image":
        raise AssertionError("HEIC 를 매직 바이트로 알아보지 못함")
    if sniff_kind(raw, "IMG_0042.HEIC") != "image":
        raise AssertionError("HEIC 를 확장자로도 알아보지 못함")


@case("L25-3", "HEIC 를 모델이 읽는 포맷으로 바꾼다")
def t_3():
    if not _has_heif():
        raise AssertionError("pillow-heif 미설치")
    out, mime, notes = prepare_photo(S.heic_bytes(), "IMG_0042.HEIC")
    if mime != "image/jpeg":
        raise AssertionError(f"HEIC 를 그대로 보냄: {mime}")
    if out[:3] != b"\xff\xd8\xff":
        raise AssertionError("결과가 JPEG 이 아님")
    if not any("HEIC" in n for n in notes):
        raise AssertionError(f"변환 사실을 기록하지 않음: {notes}")


@case("L25-4", "큰 사진을 한도 안으로 줄인다")
def t_4():
    raw = S.phone_jpeg_bytes(4032, 3024)
    out, mime, notes = prepare_photo(raw, "IMG_4821.JPG")
    if len(out) > _PHOTO_MAX_BYTES:
        raise AssertionError(f"{len(out)/1e6:.1f}MB - 한도를 넘김")
    from PIL import Image
    w, h = Image.open(io.BytesIO(out)).size
    if max(w, h) > _PHOTO_MAX_EDGE:
        raise AssertionError(f"긴 변 {max(w, h)}px - 줄이지 않음")
    if mime != "image/jpeg":
        raise AssertionError(f"mime 이 어긋남: {mime}")


@case("L25-5", "세로로 찍은 사진의 회전을 픽셀에 반영한다")
def t_5():
    # Orientation=6 = "시계방향 90도 돌려서 보라". 반영하지 않으면 모델은 누운
    # 표를 읽습니다 - 열이 행처럼 보입니다.
    raw = S.phone_jpeg_bytes(2400, 1800, orientation=6)
    from PIL import Image
    before = Image.open(io.BytesIO(raw)).size
    out, _, notes = prepare_photo(raw, "IMG_0001.JPG")
    after = Image.open(io.BytesIO(out)).size
    if before[0] <= before[1]:
        raise AssertionError("샘플이 가로 사진이 아님 - 검사가 무의미")
    if after[0] >= after[1]:
        raise AssertionError(
            f"회전 표시를 무시함: {before} 그대로 {after} - 모델이 누운 표를 봄")
    tag = Image.open(io.BytesIO(out)).getexif().get(0x0112)
    if tag not in (None, 1):
        raise AssertionError(f"회전 표시가 남아 두 번 돌아감: orientation={tag}")


@case("L25-6", "이미 작고 반듯한 그림은 건드리지 않는다")
def t_6():
    # 화면 캡처 PNG 를 굳이 JPEG 로 다시 구우면 글자만 뭉갭니다.
    raw = S.png_bytes(1200, 800)
    out, mime, notes = prepare_photo(raw, "shot.png")
    if out is not raw:
        raise AssertionError(f"손댈 필요가 없는데 다시 인코딩함: {notes}")
    if mime != "image/png":
        raise AssertionError(f"mime 이 바뀜: {mime}")


@case("L25-7", "사진 한 장으로 거래조건이 나온다")
def t_7():
    # 파이프라인이 사진을 vision 경로로 보내고, 추출 결과가 프라이싱할 수 있는
    # 모양으로 돌아오는지. 모델은 대역이고, 받은 바이트를 기록합니다.
    seen = {}

    def _extractor(payload):
        seen["bytes"] = payload
        return _stub("TS-B")("")

    out = process_termsheet(S.phone_jpeg_bytes(4032, 3024),
                            extractor=_extractor, filename="IMG_4821.JPG")
    if not out.get("supported"):
        raise AssertionError(f"평가 불가로 떨어짐: {out.get('unsupported_reason')}")

    # 모델에 간 것은 원본이 아니라 손본 사진이어야 합니다.
    if seen["bytes"][:3] != b"\xff\xd8\xff":
        raise AssertionError("모델에 JPEG 이 가지 않음")
    if len(seen["bytes"]) > _PHOTO_MAX_BYTES:
        raise AssertionError("줄이지 않은 원본이 그대로 감")

    t = out["ticket_draft"]
    for field in ("notionalDisplay", "coupon", "effectiveDate", "maturityDate"):
        if not t.get(field):
            raise AssertionError(f"프라이싱에 필요한 {field} 가 비어 있음")


@case("L25-8", "HEIC 사진 한 장도 끝까지 간다")
def t_8():
    if not _has_heif():
        raise AssertionError("pillow-heif 미설치")
    seen = {}

    def _extractor(payload):
        seen["bytes"] = payload
        return _stub("TS-B")("")

    out = process_termsheet(S.heic_bytes(), extractor=_extractor,
                            filename="IMG_0042.HEIC")
    if not out.get("supported"):
        raise AssertionError(f"HEIC 가 평가 불가로 떨어짐: {out.get('unsupported_reason')}")
    if seen["bytes"][:3] != b"\xff\xd8\xff":
        raise AssertionError("HEIC 가 변환되지 않고 모델에 감")


@case("L25-9", "사진 경로가 꺼져 있으면 그 사실을 말한다")
def t_9():
    saved = os.environ.get("TERMSHEET_ALLOW_IMAGE")
    os.environ["TERMSHEET_ALLOW_IMAGE"] = "0"
    try:
        try:
            process_termsheet(S.phone_jpeg_bytes(1200, 900),
                              extractor=lambda p: _stub("TS-B")(""),
                              filename="IMG_1.JPG")
        except ValueError as e:
            if "TERMSHEET_ALLOW_IMAGE" not in str(e):
                raise AssertionError(f"원인을 짚어주지 않음: {e}")
        else:
            raise AssertionError("꺼져 있는데 그냥 처리함")
    finally:
        if saved is None:
            os.environ.pop("TERMSHEET_ALLOW_IMAGE", None)
        else:
            os.environ["TERMSHEET_ALLOW_IMAGE"] = saved


@case("L25-10", "배포본에서 사진 경로가 켜져 있다")
def t_10():
    # 로컬에서만 되고 배포본에서 막히면, 트레이더 손에서는 없는 기능입니다.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with io.open(os.path.join(root, "render.yaml"), encoding="utf-8") as f:
        y = f.read()
    import re
    m = re.search(r"TERMSHEET_ALLOW_IMAGE\s*\n\s*value:\s*\"?(\w+)\"?", y)
    if not m:
        raise AssertionError("render.yaml 에 TERMSHEET_ALLOW_IMAGE 가 없음")
    if m.group(1) not in ("1", "true", "yes", "on"):
        raise AssertionError(f"배포본에서 꺼져 있음: {m.group(1)!r}")


@case("L25-11", "배포 의존성에 HEIC 지원이 들어 있다")
def t_11():
    # pillow-heif 가 빠지면 아이폰 사진만 조용히 실패합니다.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for name in ("requirements-deploy.txt", "requirements.txt"):
        with io.open(os.path.join(root, name), encoding="utf-8") as f:
            if "pillow-heif" not in f.read():
                raise AssertionError(f"{name} 에 pillow-heif 가 없음")


if __name__ == "__main__":
    print("\n=== L25 폰으로 찍은 사진 ===")
    sys.exit(1 if run_all("L25") else 0)
