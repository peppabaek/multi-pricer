# -*- coding: utf-8 -*-
"""
L28 eikon 로그 파일.

프로젝트 루트와 tests/ 에 pyeikon.<날짜>.<시각>.log 가 1,326개, 190MB 쌓여
있었습니다. 테스트를 한 번 돌릴 때마다 수십 개가 더 생겼습니다.

원인은 초기화 때마다 무조건 부르던 한 줄이었습니다:

    self._ek.set_log_level(1)

eikon 문서는 "By default, logs are disabled" 이고 인자는 파이썬 로깅 레벨입니다.
1 은 NOTSET(0) 바로 위 - 최소가 아니라 **최대 상세** 입니다. 로그를 줄이려고
넣은 것처럼 보이는 호출이 사실은 켜고 있었습니다.

실측으로 확인했습니다: 부르지 않으면 파일 0개, 부르면 초기화마다 1개.
"""
import glob
import io
import os
import sys

from harness import case, run_all

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def source():
    with io.open(os.path.join(ROOT, "server", "eikon_rate_limiter.py"),
                 encoding="utf-8") as f:
        return f.read()


@case("L28-1", "로깅을 무조건 켜지 않는다")
def t_1():
    src = source()
    # 조건 없이 부르는 곳이 있으면 안 됩니다. opt-in 경로 안에 있는 것은 괜찮습니다.
    i = src.find("def _configure_eikon_logging")
    if i < 0:
        raise AssertionError("로깅 설정이 한곳에 모여 있지 않음")
    outside = src[:i] + src[src.find("\ndef ", i + 10):]
    if "set_log_level(" in outside:
        raise AssertionError(
            "opt-in 경로 밖에서 set_log_level 을 부름 — 로그가 무조건 켜집니다")


@case("L28-2", "켜지 않으면 작업 폴더에 로그가 생기지 않는다")
def t_2():
    # 이 테스트 자체가 증거입니다. eikon 을 초기화해 보고 파일이 생기는지 봅니다.
    before = set(glob.glob(os.path.join(ROOT, "pyeikon.*.log*")))
    saved = os.environ.pop("PRICER_EIKON_LOG", None)
    try:
        import server.eikon_rate_limiter as m
        m.eikon_manager._initialized = False
        m.eikon_manager._ensure_init()
    except Exception:
        pass
    finally:
        if saved is not None:
            os.environ["PRICER_EIKON_LOG"] = saved
    after = set(glob.glob(os.path.join(ROOT, "pyeikon.*.log*")))
    new = after - before
    if new:
        raise AssertionError(
            f"작업 폴더에 로그가 생김: {[os.path.basename(p) for p in new]}")


@case("L28-3", "켤 수는 있어야 하고, 켜면 logs/eikon 으로 간다")
def t_3():
    # 끄기만 하면 LSEG 연결을 들여다볼 방법이 없어집니다.
    src = source()
    if "PRICER_EIKON_LOG" not in src:
        raise AssertionError("로깅을 켤 방법이 없음 — 진단이 불가능해집니다")
    if "set_log_path" not in src:
        raise AssertionError("켰을 때 어디로 갈지 정하지 않음")
    # 독스트링이 옛 동작을 설명하므로 거기부터 세면 안 됩니다 - 실제 코드만 봅니다.
    i = src.find("def _configure_eikon_logging")
    body = src[i:i + 2000]
    doc_end = body.find('"""', body.find('"""') + 3)
    code = body[doc_end + 3:] if doc_end > 0 else body
    at_path, at_level = code.find("set_log_path"), code.find("set_log_level(")
    if at_path < 0 or at_level < 0:
        raise AssertionError("켜는 경로에 set_log_path / set_log_level 이 없음")
    if at_path > at_level:
        raise AssertionError("경로보다 레벨을 먼저 설정하면 첫 파일이 작업 폴더에 생김")


@case("L28-4", "쌓인 로그를 나이와 개수로 정리한다")
def t_4():
    import server.eikon_rate_limiter as m
    if not hasattr(m, "_sweep_eikon_logs"):
        raise AssertionError("정리 루틴이 없음")
    # 나이만으로는 부족했습니다 - 7일치가 500개를 넘었습니다.
    if not hasattr(m, "_EIKON_LOG_KEEP_MAX"):
        raise AssertionError("개수 상한이 없음 — 테스트 한 번에 수십 개가 생깁니다")
    if m._EIKON_LOG_KEEP_MAX > 200:
        raise AssertionError(f"상한이 너무 큼: {m._EIKON_LOG_KEEP_MAX}")


@case("L28-5", "작업 폴더가 깨끗하다")
def t_5():
    for where in (ROOT, os.path.join(ROOT, "tests")):
        found = glob.glob(os.path.join(where, "pyeikon.*.log*"))
        if found:
            raise AssertionError(
                f"{os.path.basename(where) or 'root'} 에 {len(found)}개 남아 있음")


@case("L28-6", "로그 폴더가 저장소에 들어가지 않는다")
def t_6():
    with io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
        ignored = f.read()
    if "logs/" not in ignored and "logs" not in ignored.split():
        raise AssertionError("logs/ 가 .gitignore 에 없음")


if __name__ == "__main__":
    print("\n=== L28 eikon 로그 파일 ===")
    sys.exit(1 if run_all("L28") else 0)
