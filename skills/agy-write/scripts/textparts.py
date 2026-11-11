"""파일 종류별 글 부분 추출과 해시 계산, 검사 제외 경로 판정을 수행합니다.

Git 커밋 훅과 ledger.py에서 호출하여 사용합니다.
"""
import ast
import difflib
import hashlib
import io
import re
import subprocess
import tempfile
import tokenize
from pathlib import Path

# 문서 파일 확장자 목록
DOC_EXT = {".md", ".markdown", ".txt", ".rst", ".html", ".htm"}
# 데이터 파일 확장자 목록
DATA_EXT = {".csv", ".tsv", ".json", ".jsonl", ".lock", ".svg"}
# 해시 주석 파일 확장자 목록
HASH_EXT = {".sh", ".bash", ".zsh", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
# 슬래시 주석 파일 확장자 목록
SLASH_EXT = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".rs", ".css", ".scss"}
# 한글 정규식
HANGUL = re.compile(r"[\uac00-\ud7a3]")
# 따옴표 문자열 정규식
QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")
# 검사 제외 경로 정규식 목록
EXEMPT = (
    re.compile(r"/\.claude/projects/[^/]+/memory/"),
    re.compile(r"^/private/tmp/claude-|^/tmp/claude-"),
    re.compile(r"(^|/)settings(\.local)?\.json$"),
)


FSTRING_START = getattr(tokenize, "FSTRING_START", None)
FSTRING_END = getattr(tokenize, "FSTRING_END", None)


def py_tokens(src: str):
    """Python 소스 코드에서 f-string을 단일 STRING 토큰으로 병합하여 토큰을 생성합니다.

    Python 3.12 이상에서 f-string이 여러 토큰으로 나뉘는 차이를 없애기 위해 f-string 전체를 STRING 토큰 하나로 합칩니다.
    Python 버전과 관계없이 같은 해시를 계산합니다.
    """
    # 줄별 시작 오프셋 계산
    offsets = [0]
    for line in src.split("\n"):
        offsets.append(offsets[-1] + len(line) + 1)
    depth, begin = 0, None
    # 토큰 순회
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if FSTRING_START is not None and tok.type == FSTRING_START:
            if depth == 0:
                begin = tok
            depth += 1
            continue
        if depth:
            if tok.type == FSTRING_END:
                depth -= 1
                if depth == 0:
                    text = src[offsets[begin.start[0] - 1] + begin.start[1]:offsets[tok.end[0] - 1] + tok.end[1]]
                    yield tokenize.TokenInfo(tokenize.STRING, text, begin.start, tok.end, begin.line)
            continue
        yield tok


def split_slash(src: str):
    """따옴표 안의 //를 주석으로 보지 않고 코드와 주석 목록을 나눕니다."""
    code, comments, i, n = [], [], 0, len(src)
    # 소스 코드 순회
    while i < n:
        c = src[i]
        if c in "\"'`":
            j = i + 1
            # 따옴표 내부 순회
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n" and c != "`":
                    break
                j += 1
            code.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            comments.append(src[i:j])
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            comments.append(src[i:j])
            code.append(" ")
            i = j
        else:
            code.append(c)
            i += 1
    return "".join(code), comments


# diff hunk 헤더 정규식
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def git_hunks(old: str, new: str) -> list:
    """git diff 명령을 실행하여 변경 hunk 목록을 반환합니다."""
    # 임시 디렉터리 생성 및 diff 실행
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "a", Path(tmp) / "b"
        a.write_text(old, encoding="utf-8")
        b.write_text(new, encoding="utf-8")
        out = subprocess.run(
            ["git", "diff", "--no-index", "--no-ext-diff", "--no-color", "--histogram", "-U0", str(a), str(b)],
            capture_output=True, text=True, encoding="utf-8",
        )
    if out.returncode not in (0, 1):
        raise OSError(out.stderr)
    hunks = []
    # 변경 hunk 순회
    for m in HUNK.finditer(out.stdout):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        nstart, ncount = int(m.group(3)), int(m.group(4) or 1)
        i1 = start if count == 0 else start - 1
        j1 = nstart if ncount == 0 else nstart - 1
        hunks.append((i1, i1 + count, j1, j1 + ncount))
    return hunks


def line_opcodes(old: str, new: str) -> list:
    """두 문자열의 줄 단위 변경 구간을 구합니다.

    git diff 명령의 histogram 알고리즘 결과로 변경 구간을 우선 계산하고 git 실행에 실패하면 difflib을 사용합니다.
    빈 줄을 기준점으로 잘못 잡아 docstring 삽입 위치가 어긋나는 문제를 방지합니다.
    범위 밖 되돌리기와 빈 줄 유지 및 커밋 게이트 줄 범위 계산에 사용합니다.
    """
    olines, nlines = old.split("\n"), new.split("\n")
    # git diff 실행
    try:
        hunks = git_hunks(old, new)
    except OSError:
        hunks = None
    if hunks is not None:
        ops, i, j = [], 0, 0
        # 변경 hunk 순회
        for i1, i2, j1, j2 in hunks:
            if i1 - i != j1 - j:
                break
            if i1 > i:
                ops.append(("equal", i, i1, j, j1))
            ops.append(("insert" if i1 == i2 else "delete" if j1 == j2 else "replace", i1, i2, j1, j2))
            i, j = i2, j2
        else:
            if len(olines) - i == len(nlines) - j:
                if i < len(olines):
                    ops.append(("equal", i, len(olines), j, len(nlines)))
                return ops
    return difflib.SequenceMatcher(None, olines, nlines, autojunk=False).get_opcodes()


def exempt(path: str) -> bool:
    """검사 제외 대상 경로인지 확인합니다."""
    return any(p.search(path) for p in EXEMPT) or Path(path).suffix.lower() in DATA_EXT


def _py(src: str) -> list:
    """Python 소스 코드에서 docstring, 주석, 한글 문자열을 추출합니다."""
    parts = []
    # 문법 분석 및 토큰 추출
    try:
        tree = ast.parse(src)
        # 구문 트리 노드 순회
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    parts.append(doc)
        # 토큰 순회
        for tok in py_tokens(src):
            if tok.type == tokenize.COMMENT and not tok.string.startswith("#!"):
                parts.append(tok.string)
            elif tok.type == tokenize.STRING and HANGUL.search(tok.string):
                parts.append(tok.string)
    except (SyntaxError, tokenize.TokenError):
        return [src]
    return parts


def _hash_style(src: str) -> list:
    """해시(#) 주석 기반 파일에서 주석과 한글 문자열을 추출합니다."""
    parts = []
    # 소스 줄 순회
    for line in src.splitlines():
        if line.startswith("#!"):
            continue
        code, sep, comment = line.partition("#")
        if sep and (not code.strip() or code.endswith((" ", "\t"))):
            parts.append(comment)
        parts += [q for q in QUOTED.findall(code) if HANGUL.search(q)]
    return parts


def _slash_style(src: str) -> list:
    """슬래시(//, /* */) 주석 기반 파일에서 주석과 한글 문자열을 추출합니다."""
    stripped, parts = split_slash(src)
    return parts + [q for q in QUOTED.findall(stripped) if HANGUL.search(q)]


def extract(path: str, src: str) -> list:
    """파일 확장자와 파일명에 맞추어 글 부분을 추출합니다."""
    ext = Path(path).suffix.lower()
    name = Path(path).name.lower()
    if ext in DOC_EXT or name.startswith("readme"):
        return [src]
    if ext == ".py":
        return _py(src)
    if ext in HASH_EXT:
        return _hash_style(src)
    if ext in SLASH_EXT:
        return _slash_style(src)
    return []


def digest(parts: list) -> str:
    """추출한 글 부분 목록의 SHA-256 해시값을 계산합니다."""
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest() if parts else ""
