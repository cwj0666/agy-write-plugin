"""agy-write 실행 진입점 모듈입니다.

사용법:
    ${CLAUDE_SKILL_DIR}/scripts/annotate.py FILE[:LOCATION][=REQUEST]...

대상 파일만 읽기 권한을 허용하여 agy를 호출합니다.
"""

import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claims import report as claim_report, review  # noqa: E402
from preserve import preserve  # noqa: E402
from textparts import line_opcodes  # noqa: E402

# 경로 및 환경 변수 설정
HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets/annotate-prompt.md"
MODEL = os.environ.get("AGY_MODEL", "")
CODE_MODEL = "gemini-3.8-flash-medium"
DOC_MODEL = "gemini-3.8-flash-medium"
TIMEOUT = int(os.environ.get("AGY_TIMEOUT", "660"))
SEP = "=====CHANGES====="
RETRIES = int(os.environ.get("AGY_RETRIES", "2"))
RANGE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
DOC_EXT = {".md", ".markdown", ".txt", ".rst", ".html", ".htm"}


def parse(spec):
    """작업 명세를 대상 경로, 위치, 요청 내용으로 분할합니다."""
    spec, _, request = spec.partition("=")
    path, location = spec, ""
    if not Path(spec).exists() and ":" in spec:
        path, _, location = spec.partition(":")
    return Path(path).resolve(), location.strip(), request.strip()


def line_ranges(location):
    """줄 범위 문자열을 분석하여 대상 줄 번호 집합을 반환합니다."""
    if not RANGE.match(location.replace(" ", "")):
        return None
    out = set()
    # 줄 범위 분할 및 집합 추가
    for part in location.replace(" ", "").split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def excerpt(text, lines):
    """지정한 줄 번호에 해당하는 본문을 줄 번호와 함께 발췌합니다."""
    rows = text.split("\n")
    return "\n".join(f"{n}: {rows[n - 1]}" for n in sorted(lines) if 0 < n <= len(rows))


def restrict(old, new, allowed):
    """허용 범위 밖의 변경 사항을 원본으로 되돌립니다."""
    olines, nlines = old.split("\n"), new.split("\n")
    out, reverted = [], 0
    # 줄 차이 순회
    for tag, i1, i2, j1, j2 in line_opcodes(old, new):
        if tag == "equal":
            out += olines[i1:i2]
            continue
        if tag == "insert":
            if i1 in allowed or i1 + 1 in allowed:
                out += nlines[j1:j2]
            else:
                reverted += j2 - j1
            continue
        flags = [n in allowed for n in range(i1 + 1, i2 + 1)]
        if all(flags):
            out += nlines[j1:j2]
        elif not any(flags):
            out += olines[i1:i2]
            reverted += max(i2 - i1, j2 - j1)
        elif i2 - i1 == j2 - j1:
            # 줄 단위 허용 여부 판정
            for k, inside in enumerate(flags):
                out.append(nlines[j1 + k] if inside else olines[i1 + k])
                reverted += 0 if inside else 1
        else:
            lead = flags.index(True)
            trail = flags[::-1].index(True)
            middle = nlines[j1 + lead:j2 - trail] if lead + trail < j2 - j1 else []
            out += olines[i1:i1 + lead] + middle + olines[i2 - trail:i2]
            reverted += lead + trail
    return "\n".join(out), reverted


def build(target, location, request):
    """프롬프트 템플릿에 대상 파일 정보와 내용을 반영합니다."""
    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("{{path}}", target.name)
        .replace("{{location}}", location_text(target, location))
        .replace("{{request}}", request)
        .replace("{{content}}", target.read_text(encoding="utf-8"))
    )


def location_text(target, location):
    """줄 범위가 지정된 경우 발췌 본문을 덧붙인 위치 문자열을 구성합니다."""
    lines = line_ranges(location)
    if not lines:
        return location
    return f"{location}\n{excerpt(target.read_text(encoding='utf-8'), lines)}"


def is_doc(target):
    """대상 파일의 문서 형식 여부를 확인합니다."""
    return target.suffix.lower() in DOC_EXT or target.name.lower().startswith("readme")


def shape(old, new):
    """생성 결과의 비정상적인 반복 줄 여부를 확인합니다."""
    before = Counter(l.strip() for l in old.splitlines())
    after = Counter(l.strip() for l in new.splitlines())
    keys = [k for k, c in before.items() if c == 1 and len(k) >= 8]
    if len(keys) >= 3 and sum(after[k] >= 2 for k in keys) * 2 > len(keys):
        return "duplicated content"
    return ""


def verify(backup, target):
    """백업 파일과 대상 파일을 비교하여 변경 사항을 검증합니다."""
    if is_doc(target):
        out = subprocess.run(["bash", str(HERE / "verify.sh"), str(backup), str(target)], capture_output=True, text=True)
        return True, out.stdout
    out = subprocess.run([sys.executable, str(HERE / "verify_code.py"), str(backup), str(target)], capture_output=True, text=True)
    return out.returncode == 0, out.stdout + out.stderr


def call(prompt, model, settings):
    """지정한 모델과 설정으로 agy 명령을 실행합니다."""
    # agy 프로세스 실행
    try:
        return subprocess.run(
            ["agy", "-p", prompt, "--model", model, "--print-timeout", "8m",
             "--disable-slash-commands", "--output-format", "text", "--settings", settings],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess([], 1, "", f"timeout after {TIMEOUT}s")
    except OSError as e:
        return subprocess.CompletedProcess([], 1, "", str(e))


def attempt(target, backup, prompt, model, settings, allowed=None, request=""):
    """단일 실행 단위로 agy를 호출하고 결과를 파일에 반영 및 검증합니다."""
    proc = call(prompt, model, settings)
    result = proc.stdout
    # 실행 결과 분기
    if f"\n{SEP}" not in f"\n{result}":
        return False, result, f"no {SEP}\n{proc.stderr[-2000:]}"
    body, _, changes = f"\n{result}".partition(f"\n{SEP}")
    if not body.strip():
        return False, result, "empty body"
    problem = shape(backup.read_text(encoding="utf-8"), body)
    if problem:
        return False, result, f"{problem} (not applied)"
    # 대상 파일 반영 및 검증
    body = body.lstrip("\n").rstrip("\n") + "\n"
    reverted = 0
    if allowed:
        body, reverted = restrict(backup.read_text(encoding="utf-8"), body, allowed)
    target.write_text(body, encoding="utf-8")
    ok, report = verify(backup, target)
    if reverted:
        report = f"{report}\noutside reverted: {reverted}"
    if not ok:
        shutil.copy2(backup, target)
        return False, result, f"RESTORED\n{report}"
    if not is_doc(target):
        generated = target.read_text(encoding="utf-8")
        merged, kept = preserve(backup.read_text(encoding="utf-8"), generated, target.name, docstrings=not request)
        if kept:
            target.write_text(merged.rstrip("\n") + "\n", encoding="utf-8")
            ok, merged_report = verify(backup, target)
            if ok:
                report = f"{merged_report}\nkept: {kept}" + (f"\noutside reverted: {reverted}" if reverted else "")
            else:
                target.write_text(generated, encoding="utf-8")
                report = f"{report}\nkept: skipped"
    checks = claim_report(review(backup.read_text(encoding="utf-8"), target.read_text(encoding="utf-8"), request, terms=is_doc(target)))
    if checks:
        report = f"{report}\n{checks}"
    return True, result, f"{report}\n{changes.strip()}"


def run(index, spec, work):
    """단일 파일에 대해 agy 호출과 결과 반영 및 검증을 수행합니다."""
    target, location, request = parse(spec)
    stem = f"{index:02d}-{target.name}"
    model = MODEL or (DOC_MODEL if is_doc(target) else CODE_MODEL)
    prompt = build(target, location, request)
    (work / f"{stem}.prompt.md").write_text(prompt, encoding="utf-8")
    # 읽기 권한 설정
    settings = json.dumps({"permissions": {"allow": [f"read_file({target})"]}})
    backup = work / f"{stem}.bak"
    shutil.copy2(target, backup)
    failures = []
    # 재시도 횟수
    for n in range(1, RETRIES + 2):
        ok, result, report = attempt(target, backup, prompt, model, settings, line_ranges(location), request)
        (work / f"{stem}.result{n}.txt").write_text(result, encoding="utf-8")
        if ok:
            subprocess.run([sys.executable, str(HERE / "ledger.py"), "record", str(target)], capture_output=True)
            return f"== OK {target}\nmodel: {model} attempts: {n}\nbackup: {backup}\n" + "".join(failures) + report
        failures.append(f"[attempt {n} NG] {report.splitlines()[0] if report else ''}\n")
    return f"== NG {target}\nmodel: {model}\n" + "".join(failures) + report


def main():
    """인자를 확인하고 대상 파일 작업을 병렬로 실행합니다."""
    specs = sys.argv[1:]
    if not specs:
        sys.exit("annotate.py FILE[:LOCATION][=REQUEST]...")
    # 작업 디렉터리 생성
    work = Path(os.environ.get("AGY_WORK") or tempfile.mkdtemp(prefix="agy-write-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"work: {work}", flush=True)
    # 병렬 처리
    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        outputs = list(pool.map(lambda a: run(a[0], a[1], work), enumerate(specs)))
    # 실행 결과
    for out in outputs:
        print(out, end="\n\n")
    sys.exit(0 if all(o.startswith("== OK") for o in outputs) else 1)


if __name__ == "__main__":
    main()
