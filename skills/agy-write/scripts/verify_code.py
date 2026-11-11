# 사용법: python3 ${CLAUDE_SKILL_DIR}/scripts/verify_code.py <이전 파일> <새 파일>
# .py 파일은 docstring 제거와 한글 문자열 가림 후 ast, tokens, layout 세 가지를 비교합니다.
# layout은 코드 줄마다 토큰을 묶어 비교하므로 괄호 안 줄 분할이나 백슬래시 줄 이음 같은 줄 배치 변경을 잡습니다.
# 여러 줄 문자열의 끝 줄에 이어지는 토큰은 문자열 시작 줄과 같은 묶음으로 봅니다.
# SLASH_EXT 확장자 파일은 따옴표 안을 제외하고 //와 /* */ 주석을 제거한 줄을 비교합니다.
# 그 밖의 파일은 # 주석 기준으로 비교합니다.
# 줄 수와 긴 하이픈 위치를 출력하며 코드가 같으면 종료 코드 0으로 종료합니다.
import ast
import re
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textparts import HANGUL, SLASH_EXT, split_slash, py_tokens as _tokens  # noqa: E402

# 문자열 리터럴 정규식
QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
# 슬래시 계열 언어 따옴표 정규식
SLASH_QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")
# 레이아웃 비교 건너뛰기 토큰
LAYOUT_SKIP = (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER)


def py_doc_stripped(src):
    """docstring을 제거하고 한글 문자열을 가린 AST 문자열을 반환합니다."""
    tree = ast.parse(src)
    # 구문 트리 순회
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = body[1:]
    # 구문 트리 순회
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and HANGUL.search(node.value):
            node.value = "<text>"
    return ast.dump(tree)


def py_doc_lines(src):
    """docstring에 해당하는 코드 줄 번호 집합을 반환합니다."""
    lines = set()
    # 구문 트리 순회
    for node in ast.walk(ast.parse(src)):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.update(range(first.lineno, first.end_lineno + 1))
    return lines


def masked(t):
    """한글 문자열 토큰의 내용을 가린 토큰 튜플을 반환합니다."""
    return (t.type, "<text>" if t.type == tokenize.STRING and HANGUL.search(t.string) else t.string)


def py_tokens(src):
    """주석과 docstring을 제외하고 한글 문자열을 가린 Python 토큰 목록을 반환합니다."""
    skip = (tokenize.COMMENT, tokenize.NL)
    doc = py_doc_lines(src)
    return [
        masked(t)
        for t in _tokens(src)
        if t.type not in skip and (t.start[0] not in doc or t.type in (tokenize.INDENT, tokenize.DEDENT))
    ]


def py_layout(src):
    """코드 줄별로 토큰을 묶어 줄 배치 구조 목록을 반환합니다."""
    doc = py_doc_lines(src)
    groups, key_of = {}, {}
    # 토큰 순회
    for t in _tokens(src):
        line = t.start[0]
        key = key_of.get(line, line)
        if t.end[0] > line:
            key_of[t.end[0]] = key
        if t.type in LAYOUT_SKIP or line in doc:
            continue
        groups.setdefault(key, []).append(masked(t))
    return list(groups.values())


def slash_lines(src):
    """슬래시 계열 언어 주석을 제거하고 한글 문자열을 가린 줄 목록을 반환합니다."""
    code, _ = split_slash(src)
    out = []
    # 줄 순회
    for line in code.splitlines():
        line = line.rstrip()
        if line.strip():
            out.append(SLASH_QUOTED.sub(lambda m: "<text>" if HANGUL.search(m.group(0)) else m.group(0), line))
    return out


def sh_lines(src):
    """샵 주석을 제거하고 한글 문자열을 가린 줄 목록을 반환합니다."""
    out = []
    # 줄 순회
    for line in src.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code = re.sub(r"\s+#\s.*$", "", line).rstrip()
        out.append(QUOTED.sub(lambda m: "<text>" if HANGUL.search(m.group(0)) else m.group(0), code))
    return out


def main():
    """두 파일의 코드를 대조해 일치 여부와 변경 정보를 출력합니다."""
    old_path, new_path = sys.argv[1], sys.argv[2]
    old, new = (open(p, encoding="utf-8").read().rstrip("\n") + "\n" for p in (old_path, new_path))
    if new_path.endswith(".py"):
        checks = {
            "ast": py_doc_stripped(old) == py_doc_stripped(new),
            "tokens": py_tokens(old) == py_tokens(new),
            "layout": py_layout(old) == py_layout(new),
        }
    elif Path(new_path).suffix.lower() in SLASH_EXT:
        checks = {"lines": slash_lines(old) == slash_lines(new)}
    else:
        checks = {"lines": sh_lines(old) == sh_lines(new)}
    checks["line_count"] = f"{old.count(chr(10))} -> {new.count(chr(10))}"
    checks["long_dash"] = [i + 1 for i, line in enumerate(new.splitlines()) if chr(0x2014) in line]
    print(checks)
    sys.exit(0 if all(v is True for k, v in checks.items() if k in ("ast", "tokens", "layout", "lines")) else 1)


if __name__ == "__main__":
    main()
