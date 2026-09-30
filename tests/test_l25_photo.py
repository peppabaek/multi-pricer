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


@case("L25-12", "여러 장을 한 문서로 읽는다")
def t_12():
    """
    Term sheet 은 여러 장으로 찍히는 일이 흔합니다 - 거래조건이 1쪽, 상각
    스케줄이 2쪽. 한 장만 읽으면 반쪽짜리 답이 나오고, 장마다 따로 추출해
    합치면 2쪽의 표가 1쪽의 거래와 이어지지 않습니다. 한 번의 호출에 전부
    실어 보냅니다.
    """
    seen = {}

    def _extractor(payload):
        seen["payload"] = payload
        return _stub("TS-B")("")

    p1, p2 = S.two_page_photos()
    out = process_termsheet(p1, extractor=_extractor, filename="p1.jpg",
                            extra_pages=[(p2, "p2.jpg")])
    if not out.get("supported"):
        raise AssertionError(f"평가 불가: {out.get('unsupported_reason')}")


@case("L25-13", "뒷장도 같은 보정을 거친다")
def t_13():
    # 1쪽만 회전·축소하고 2쪽은 원본 그대로 보내면, 2쪽이 누워 있거나 한도를
    # 넘깁니다. 모델에 실제로 전달되는 것을 봅니다.
    sent = {}

    def fake_vision(raw, mime, used=None):
        sent["pages"] = raw
        return _stub("TS-B")("")

    import server.termsheet as T
    saved = T.call_vision_extractor
    T.call_vision_extractor = fake_vision
    try:
        big = S.phone_jpeg_bytes(4032, 3024, orientation=6)
        T.process_termsheet(big, filename="p1.jpg",
                            extra_pages=[(big, "p2.jpg"), (big, "p3.jpg")])
    finally:
        T.call_vision_extractor = saved

    pages = sent.get("pages")
    if not isinstance(pages, (list, tuple)):
        raise AssertionError(f"여러 장인데 목록으로 전달되지 않음: {type(pages).__name__}")
    if len(pages) != 3:
        raise AssertionError(f"{len(pages)}장만 전달됨")
    from PIL import Image
    for i, (data, mime) in enumerate(pages, 1):
        if mime != "image/jpeg" or data[:3] != b"\xff\xd8\xff":
            raise AssertionError(f"{i}쪽이 JPEG 이 아님: {mime}")
        if len(data) > _PHOTO_MAX_BYTES:
            raise AssertionError(f"{i}쪽이 줄지 않음: {len(data)/1e6:.1f}MB")
        w, h = Image.open(io.BytesIO(data)).size
        if max(w, h) > _PHOTO_MAX_EDGE:
            raise AssertionError(f"{i}쪽 긴 변 {max(w,h)}px")
        if w >= h:
            raise AssertionError(f"{i}쪽 회전 보정이 안 됨: {w}x{h}")


@case("L25-14", "한 장일 때는 전과 똑같이 보낸다")
def t_14():
    # 여러 장을 지원하느라 한 장 경로가 바뀌면, 이미 돌던 것이 조용히 달라집니다.
    sent = {}

    def fake_vision(raw, mime, used=None):
        sent["raw"] = raw
        return _stub("TS-B")("")

    import server.termsheet as T
    saved = T.call_vision_extractor
    T.call_vision_extractor = fake_vision
    try:
        T.process_termsheet(S.phone_jpeg_bytes(1400, 1050), filename="one.jpg")
    finally:
        T.call_vision_extractor = saved

    if isinstance(sent.get("raw"), (list, tuple)):
        raise AssertionError("한 장인데 목록으로 감 — 기존 경로가 바뀜")


@case("L25-15", "여러 장 업로드가 엔드포인트까지 이어진다")
def t_15():
    from fastapi.testclient import TestClient
    import server.termsheet as T
    from server.app import app

    got = {}

    def fake(raw, mime, used=None):
        got["n"] = len(raw) if isinstance(raw, (list, tuple)) else 1
        return _stub("TS-B")("")

    saved = T.call_vision_extractor
    T.call_vision_extractor = fake
    try:
        p1, p2 = S.two_page_photos()
        r = TestClient(app).post("/api/termsheet/extract", files=[
            ("files", ("p1.jpg", p1, "image/jpeg")),
            ("files", ("p2.jpg", p2, "image/jpeg"))])
    finally:
        T.call_vision_extractor = saved

    if r.status_code != 200:
        raise AssertionError(f"HTTP {r.status_code}: {r.text[:150]}")
    if got.get("n") != 2:
        raise AssertionError(f"모델에 {got.get('n')}장만 전달됨")


@case("L25-16", "사진과 PDF 를 섞어 올리면 막는다")
def t_16():
    # 여러 장은 사진 경로에서만 뜻이 있습니다. PDF 를 섞으면 텍스트 경로와
    # 이미지 경로가 한 요청에 뒤섞여, 무엇이 읽혔는지 말할 수 없게 됩니다.
    from fastapi.testclient import TestClient
    from server.app import app
    r = TestClient(app).post("/api/termsheet/extract", files=[
        ("files", ("a.jpg", S.phone_jpeg_bytes(800, 600), "image/jpeg")),
        ("files", ("b.pdf", S.scanned_pdf_bytes(), "application/pdf"))])
    if r.status_code == 200:
        raise AssertionError("섞어 올렸는데 그냥 처리함")


if __name__ == "__main__":
    print("\n=== L25 폰으로 찍은 사진 ===")
    sys.exit(1 if run_all("L25") else 0)
