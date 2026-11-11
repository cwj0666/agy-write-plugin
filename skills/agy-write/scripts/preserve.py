"""규칙에 맞는 주석과 docstring 및 빈 줄 배치를 복원합니다."""

import ast
import re
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textparts import HANGUL, HASH_EXT, SLASH_EXT, extract, line_opcodes, py_tokens  # noqa: E402
from verify_code import LAYOUT_SKIP, py_doc_lines  # noqa: E402

# 문장 종결 패턴
SENTENCE = re.compile(r"(다|요)\.?$")
# 지시 주석 패턴
DIRECTIVE = re.compile(r"^(!|noqa|type:|pragma|pylint:|fmt:|eslint|@ts-|istanbul|prettier|shellcheck)")
# 금지 문자 패턴
FORBIDDEN = re.compile("[\u2014\U0001F300-\U0001FAFF\u2705\u274C]")
# docstring 대상 AST 노드
DOC_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def label_ok(text):
    """코드 옆 주석의 규칙 부합 여부를 검사합니다."""
    t = text.strip()
    if DIRECTIVE.match(t):
        return True
    return bool(HANGUL.search(t)) and not SENTENCE.search(t) and not t.endswith(".") and not FORBIDDEN.search(t)


def sentence_ok(text):
    """설명 문장의 종결 형태와 금지 문자 포함 여부를 검사합니다."""
    t = text.strip()
    return bool(HANGUL.search(t)) and t.endswith("다.") and not FORBIDDEN.search(t)


def docstring_ok(text):
    """docstring 첫 줄 문장의 종결 규칙 부합 여부를 검사합니다."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return bool(lines) and sentence_ok(lines[0]) and not FORBIDDEN.search(text)


def block_ok(lines, style):
    """주석 블록의 규칙 부합 여부를 검사합니다."""
    raw = "\n".join(l.strip() for l in lines)
    if style == "hash":
        return all(label_ok(l.strip()[1:]) for l in lines)
    if raw.startswith("//"):
        return all(label_ok(l.strip()[2:]) for l in lines)
    jsdoc = raw.startswith("/**")
    # 주석 줄 순회
    for l in lines:
        t = l.strip()
        # 주석 기호 순회
        for mark in ("/**", "/*", "*/"):
            t = t.replace(mark, "")
        t = t.strip().lstrip("*").strip()
        if not t:
            continue
        if t.startswith("@"):
            desc = re.sub(r"^@\w+\s*(\{[^}]*\})?\s*", "", t)
            if t.startswith("@param"):
                desc = re.sub(r"^(\[[^\]]*\]|[\w.$]+)\s*-?\s*", "", desc)
            if desc and (SENTENCE.search(desc) or FORBIDDEN.search(desc)):
                return False
        elif not (sentence_ok(t) if jsdoc else label_ok(t)):
            return False
    return True


def py_units(src):
    """Python 소스 코드에서 토큰 기반 코드 줄과 주석 단위를 추출합니다."""
    lines = src.split("\n")
    doc = py_doc_lines(src)
    keys, key_of, seen, comments = [], {}, set(), []
    # 토큰 순회
    for t in py_tokens(src):
        line = t.start[0]
        key = key_of.get(line, line)
        if t.end[0] > line:
            key_of[t.end[0]] = key
        if t.type == tokenize.COMMENT:
            comments.append((line, t.start[1], t.string))
            continue
        if t.type in LAYOUT_SKIP or line in doc:
            continue
        if key not in seen:
            seen.add(key)
            keys.append(key)
    code_of = {}
    # 코드 줄 순회
    for line in range(1, len(lines) + 1):
        k = key_of.get(line, line)
        if k in seen:
            code_of[line] = keys.index(k)
    full = {}
    trail = []
    # 주석 항목 순회
    for line, col, text in comments:
        if lines[line - 1][:col].strip():
            if line in code_of:
                trail.append((code_of[line], line, col, text[1:]))
        else:
            full[line] = text
    return lines, keys, code_of, full, trail


def line_units(src, style):
    """문자열과 주석 위치를 추적해 코드 줄과 주석 단위를 분리합니다."""
    lines = src.split("\n")
    flags = [[False] * len(l) for l in lines]
    pos = [(i, j) for i, l in enumerate(lines) for j in range(len(l) + 1)]
    i, n = 0, len(src)

    def mark(a, b):
        """지정 범위의 위치를 주석 플래그로 설정합니다."""
        # 범위 내 위치 순회
        for k in range(a, b):
            li, co = pos[k]
            if co < len(lines[li]):
                flags[li][co] = True

    # 소스 문자 순회
    while i < n:
        c = src[i]
        if c in "\"'" or (style == "slash" and c == "`"):
            j = i + 1
            # 따옴표 종결 위치 순회
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n" and c != "`":
                    break
                j += 1
            i = j + 1
        elif style == "slash" and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            mark(i, j)
            i = j
        elif style == "slash" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            mark(i, j)
            i = j
        elif style == "hash" and c == "#" and (i == 0 or src[i - 1] in " \t\n"):
            j = src.find("\n", i)
            j = n if j < 0 else j
            mark(i, j)
            i = j
        else:
            i += 1
    keys, code_of, full, trail = [], {}, {}, []
    # 줄 단위 코드 및 주석 순회
    for li, l in enumerate(lines):
        code = "".join(ch for ch, f in zip(l, flags[li]) if not f)
        has_comment = any(flags[li])
        line = li + 1
        if code.strip():
            code_of[line] = len(keys)
            keys.append(line)
            if has_comment:
                col = flags[li].index(True)
                trail.append((code_of[line], line, col, l[col:]))
        elif has_comment:
            full[line] = l
    return lines, keys, code_of, full, trail


def anchors(units):
    """코드 줄 순번을 기준으로 전체 줄 주석 블록과 줄 끝 주석을 대응시킵니다."""
    lines, keys, code_of, full, trail = units
    blocks = {}
    line = 1
    # 소스 줄 순회
    while line <= len(lines):
        if line in full:
            start = line
            # 연속 전체 줄 주석 순회
            while line + 1 in full:
                line += 1
            nxt = next((i for i, k in enumerate(keys) if k > line), None)
            if nxt is not None:
                blocks[nxt] = (start, line)
        line += 1
    trails = {}
    # 줄 끝 주석 순회
    for idx, line, col, text in trail:
        trails.setdefault(idx, (line, col, text))
    return blocks, trails


def first_line(code_of, idx):
    """코드 순번에 대응하는 첫 번째 줄 번호를 반환합니다."""
    return min(l for l, i in code_of.items() if i == idx)


def merge_comments(old, new, style, docstrings=True):
    """원본 주석 중 규칙에 맞는 주석을 새 코드에 병합합니다."""
    if style == "py":
        ou, nu = py_units(old), py_units(new)
    else:
        ou, nu = line_units(old, style), line_units(new, style)
    if len(ou[1]) != len(nu[1]):
        return new, 0
    olines, nlines = ou[0], list(nu[0])
    ob, ot = anchors(ou)
    nb, nt = anchors(nu)
    edits, kept = [], 0
    check = "hash" if style in ("py", "hash") else "slash"
    # 원본 줄 끝 주석 순회
    for idx, (oline, ocol, otext) in ot.items():
        text = otext if style != "py" else "#" + otext
        ok = label_ok(otext) if style == "py" else block_ok([text], check)
        if not ok:
            continue
        if idx in nt:
            nline, ncol, ntext = nt[idx]
            if ntext == otext:
                continue
            body = nlines[nline - 1][:ncol]
        else:
            nline = first_line(nu[2], idx)
            body = nlines[nline - 1]
        spacing = olines[oline - 1][:ocol]
        spacing = spacing[len(spacing.rstrip()):] or "  "
        edits.append((nline - 1, nline, [body.rstrip() + spacing + (olines[oline - 1][ocol:])]))
        kept += 1
    # 원본 전체 줄 주석 블록 순회
    for idx, (os_, oe) in ob.items():
        oblock = olines[os_ - 1:oe]
        if not block_ok(oblock, check):
            continue
        if idx in nb:
            ns, ne = nb[idx]
            if nlines[ns - 1:ne] == oblock:
                continue
            if not docstrings and style == "slash" and oblock[0].strip().startswith("/*") and nlines[ns - 1].strip().startswith("/*"):
                continue
            edits.append((ns - 1, ne, oblock))
        else:
            at = first_line(nu[2], idx) - 1
            edits.append((at, at, oblock))
        kept += 1
    return apply(nlines, edits), kept


def merge_docstrings(old, new):
    """원본 docstring 중 규칙에 맞는 내용을 새 코드에 병합합니다."""
    def docs(src):
        """소스 코드의 AST 노드에서 docstring 위치와 내용을 추출합니다."""
        out = []
        # AST 노드 순회
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, DOC_NODES):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    out.append((first.lineno, first.end_lineno, first.value.value))
                else:
                    out.append(None)
        return out

    od, nd = docs(old), docs(new)
    if len(od) != len(nd):
        return new, 0
    olines, nlines = old.split("\n"), new.split("\n")
    edits, kept = [], 0
    # docstring 목록 순회
    for o, n in zip(od, nd):
        if not o or not n or o[2] == n[2] or not docstring_ok(o[2]):
            continue
        ostart, oend = o[0], o[1]
        quotes = ('"', "'", 'r"', "r'", 'u"', "u'")
        if not olines[ostart - 1].lstrip().startswith(quotes) or not nlines[n[0] - 1].lstrip().startswith(quotes):
            continue
        edits.append((n[0] - 1, n[1], olines[ostart - 1:oend]))
        kept += 1
    return apply(nlines, edits), kept


def apply(lines, edits):
    """수정 목록을 역순으로 줄 목록에 반영합니다."""
    edits.sort(key=lambda e: (e[0], e[1]), reverse=True)
    last = None
    # 편집 항목 순회
    for start, end, repl in edits:
        if last is not None and end > last:
            continue
        lines[start:end] = repl
        last = start
    return "\n".join(lines)


def blank_lines(old, new, name):
    """텍스트 내용 변경 없이 빈 줄만 추가되거나 삭제된 구간을 원본으로 되돌립니다."""
    olines, nlines = old.split("\n"), new.split("\n")
    out, changed = [], 0
    ops = line_opcodes(old, new)
    # 차이 구간 순회
    for tag, i1, i2, j1, j2 in ops:
        if tag == "insert" and all(not l.strip() for l in nlines[j1:j2]):
            changed += j2 - j1
            continue
        if tag == "delete" and all(not l.strip() for l in olines[i1:i2]):
            out += olines[i1:i2]
            changed += i2 - i1
            continue
        out += nlines[j1:j2]
    result = "\n".join(out)
    if not changed or extract(name, result) != extract(name, new):
        return new, 0
    return result, changed


def preserve(old, new, name, docstrings=True):
    """원본 파일과 새 파일을 비교해 규칙에 맞는 글과 빈 줄 배치를 복원합니다."""
    ext = Path(name).suffix.lower()
    # 복원 처리 시도
    try:
        if ext == ".py" or ext in SLASH_EXT or ext in HASH_EXT:
            new, blanks = blank_lines(old, new, name)
        else:
            blanks = 0
        if ext == ".py":
            merged, a = merge_docstrings(old, new) if docstrings else (new, 0)
            merged, b = merge_comments(old, merged, "py")
            return merged, a + b + blanks
        if ext in SLASH_EXT:
            merged, b = merge_comments(old, new, "slash", docstrings)
            return merged, b + blanks
        if ext in HASH_EXT:
            merged, b = merge_comments(old, new, "hash")
            return merged, b + blanks
    except (SyntaxError, tokenize.TokenError, ValueError, IndexError):
        pass
    return new, 0


if __name__ == "__main__":
    old, new = (open(p, encoding="utf-8").read() for p in sys.argv[1:3])
    merged, kept = preserve(old, new, sys.argv[2])
    sys.stdout.write(merged)
    print(f"\n[kept {kept}]", file=sys.stderr)
