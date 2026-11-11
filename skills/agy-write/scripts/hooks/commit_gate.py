"""PreToolUse Bash 훅 스크립트입니다.

셸 구분자 단위로 명령을 분할하여 실제 커밋 명령일 때만 검사를 수행합니다.
따옴표 안 문자열에 포함된 단어는 검사 대상에서 제외합니다.
따옴표가 짝이 맞지 않으면 정규식으로 커밋 명령 여부를 판정합니다.
글 영역 내용이 원장 기록과 다른 파일이 있으면 실행을 차단합니다.

검사 대상은 이번 커밋에 들어갈 내용입니다.
기본은 stage된 내용이고 -a 옵션이면 추적 중인 수정 파일 전체이며 경로를 지정하면 해당 경로만 검사합니다.
병합, 체리픽, 되돌리기, 리베이스 중이면 MERGE_HEAD, CHERRY_PICK_HEAD, REVERT_HEAD, REBASE_HEAD의 상대편 내용과 같은 글은 팀원이 이미 쓴 글로 보고 제외합니다.
차단 시에는 HEAD와 상대편 모두에 없는 새 줄만 파일:줄 범위 형식으로 안내합니다.
제외 목록은 git 공통 디렉터리의 info/agy-write-ignore 파일(.git/info/agy-write-ignore)이며 커밋되지 않는 개인 설정입니다. worktree에서도 원래 저장소의 목록을 쓰도록 git rev-parse --git-common-dir 기준으로 찾습니다. /로 끝나는 항목은 폴더, 나머지는 파일 이름 패턴입니다.

사용법:
    ${CLAUDE_SKILL_DIR}/scripts/hooks/commit_gate.py
"""

import json
import re
import shlex
import subprocess
import sys
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

# 프로젝트 루트 경로
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ledger import recorded  # noqa: E402
from textparts import digest, exempt, extract, line_opcodes  # noqa: E402

# 커밋 명령 정규식
COMMIT = re.compile(r"\bgit\b[^;&|]*\bcommit\b")
# 명령 분할 구분자
SEPARATORS = ";&|()\n"
# git 전역 값 옵션
VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# 커밋 단축 값 옵션
SHORT_VALUE = set("mFCct")
# 커밋 단축 부착 옵션
SHORT_ATTACHED = set("Su")
# 커밋 긴 값 옵션
LONG_VALUE = {"--message", "--file", "--reuse-message", "--reedit-message", "--author", "--date",
              "--template", "--fixup", "--squash", "--cleanup", "--trailer", "--pathspec-from-file"}
# 상대편 참조 목록
OTHER_HEADS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD")
# 무시 규칙 파일 이름
IGNORE_FILE = "info/agy-write-ignore"


def segments(command: str) -> list:
    """명령 문자열을 구분자 단위 세그먼트 목록으로 분할합니다."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=SEPARATORS)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    out, cur = [], []
    # 토큰 순회
    for tok in lex:
        if tok and all(c in SEPARATORS for c in tok):
            out.append(cur)
            cur = []
        else:
            cur.append(tok)
    out.append(cur)
    return out


def commit_args(command: str):
    """명령 문자열에서 git commit 뒤의 인자 목록을 추출합니다."""
    # 세그먼트 파싱
    try:
        parts = segments(command)
    except ValueError:
        return [] if COMMIT.search(command) else None
    # 세그먼트 순회
    for seg in parts:
        while seg and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[0]):
            seg = seg[1:]
        if not seg or Path(seg[0]).name != "git":
            continue
        i = 1
        while i < len(seg) and seg[i].startswith("-"):
            i += 2 if seg[i] in VALUE_OPTIONS else 1
        if i < len(seg) and seg[i] == "commit":
            return seg[i + 1:]
    return None


def is_commit(command: str) -> bool:
    """명령 문자열이 커밋 명령인지 확인합니다."""
    return commit_args(command) is not None


def commit_scope(args: list):
    """커밋 명령 인자에서 -a 옵션 여부와 대상 경로 목록을 구합니다.

    -m 같은 값 옵션의 값은 경로로 보지 않습니다.
    """
    every, paths, i, rest = False, [], 0, False
    # 인자 순회
    while i < len(args):
        a = args[i]
        if rest:
            paths.append(a)
        elif a == "--":
            rest = True
        elif a.startswith("--"):
            name = a.split("=", 1)[0]
            if name == "--all":
                every = True
            elif "=" not in a and name in LONG_VALUE:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            # 단축 옵션 문자 순회
            for k, ch in enumerate(a[1:]):
                if ch == "a":
                    every = True
                if ch in SHORT_ATTACHED:
                    break
                if ch in SHORT_VALUE:
                    if k == len(a) - 2:
                        i += 1
                    break
        else:
            paths.append(a)
        i += 1
    return every, paths


def git(cwd: str, *args: str) -> str:
    """지정한 작업 디렉터리에서 git 명령을 실행하고 표준 출력을 반환합니다."""
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True).stdout


def names(out: str) -> list:
    """NUL 구분자로 출력된 파일 이름 문자열을 목록으로 변환합니다."""
    return [n for n in out.split("\0") if n]


def changed_files(cwd: str, every: bool = False, paths: list = ()) -> list:
    """커밋 대상 변경 파일 목록을 조회합니다."""
    top = git(cwd, "rev-parse", "--show-toplevel").strip()
    if not top:
        return []
    if paths:
        found = names(git(cwd, "diff", "HEAD", "--name-only", "-z", "--diff-filter=d", "--", *paths))
        return [(top, n, "worktree") for n in found]
    staged = names(git(top, "diff", "--cached", "--name-only", "-z", "--diff-filter=d"))
    if not every:
        return [(top, n, "index") for n in staged]
    tracked = names(git(top, "diff", "--name-only", "-z", "--diff-filter=d"))
    return [(top, n, "worktree") for n in dict.fromkeys(staged + tracked)]


def other_heads(top: str) -> list:
    """진행 중인 작업의 상대편 HEAD 커밋 해시 목록을 반환합니다."""
    out = []
    # 상대편 참조 이름 순회
    for name in OTHER_HEADS:
        sha = git(top, "rev-parse", "-q", "--verify", name).strip()
        if sha:
            out.append(sha)
    return out


@lru_cache(maxsize=None)
def ignore_file(top: str) -> Path:
    """git 공통 디렉터리의 제외 목록 파일 경로를 반환합니다.

    파일마다 git을 다시 호출하지 않도록 저장소별로 결과를 캐시합니다. worktree에서도 원래 저장소의 목록을 쓰도록 git rev-parse --git-common-dir 기준으로 찾습니다.
    """
    common = git(top, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / IGNORE_FILE


def ignored(top: str, name: str) -> bool:
    """파일이 무시 규칙 파일에 정의된 제외 패턴에 부합하는지 확인합니다."""
    rules = ignore_file(top)
    if not rules.is_file():
        return False
    # 무시 규칙 줄 순회
    for raw in rules.read_text(encoding="utf-8").splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        rule = rule.lstrip("/")
        if rule.endswith("/"):
            if name.startswith(rule) or f"/{rule}" in f"/{name}":
                return True
        elif fnmatch(name, rule) or fnmatch(Path(name).name, rule):
            return True
    return False


def added_lines(old: str, new: str) -> set:
    """추가되거나 교체된 줄 번호 집합을 구합니다.

    삭제만 있는 변경은 제외합니다.
    """
    out = set()
    # 줄 차이 연산 순회
    for tag, _, _, j1, j2 in line_opcodes(old, new):
        if tag in ("replace", "insert"):
            out.update(range(j1 + 1, j2 + 1))
    return out


def ranges(lines: list) -> str:
    """줄 번호 목록을 쉼표로 구분한 연속 범위 문자열로 변환합니다."""
    out, start, prev = [], None, None
    # 줄 번호 순회
    for n in sorted(lines):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev > start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev > start else str(start))
    return ",".join(out)


# 원장 미기록 파일 목록
def pending(cwd: str, every: bool = False, paths: list = ()) -> list:
    """원장에 기록되지 않은 변경 파일과 줄 범위 목록을 반환합니다."""
    out = []
    files = changed_files(cwd, every, paths)
    others = other_heads(files[0][0]) if files else []
    # 변경 파일 순회
    for top, name, source in files:
        path = Path(top) / name
        if exempt(str(path)) or ignored(top, name) or not path.is_file():
            continue
        # 파일 내용 읽기
        try:
            disk = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        content = git(top, "show", f":{name}") if source == "index" else disk
        if not content:
            continue
        now = extract(name, content)
        if not now:
            continue
        base = git(top, "show", f"HEAD:{name}")
        sides = [base] + [git(top, "show", f"{sha}:{name}") for sha in others]
        if any(now == extract(name, side) for side in sides) or digest(now) == recorded(path.resolve()):
            continue
        mine = added_lines(base, disk)
        # 상대편 내용 줄 차이 제외
        for side in sides[1:]:
            mine &= added_lines(side, disk)
        if not mine:
            continue
        out.append(f"{path}:{ranges(mine)}")
    return out


# 커밋 차단 판정
def main():
    """커밋 명령을 검사하여 미기록 파일이 있을 때 실행을 차단합니다."""
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command", "")
    args = commit_args(command)
    if args is None:
        return
    every, paths = commit_scope(args)
    files = pending(data.get("cwd") or ".", every, paths)
    if not files:
        return
    messages = json.loads((ROOT / "assets/messages.json").read_text(encoding="utf-8"))
    reason = (messages["commit_deny"]
              .replace("{files}", "\n".join(files))
              .replace("{ledger}", str(ROOT / "scripts/ledger.py")))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
