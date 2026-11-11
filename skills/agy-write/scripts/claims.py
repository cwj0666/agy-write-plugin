"""사실 확인 대상 문장 목록을 추출합니다."""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textparts import line_opcodes  # noqa: E402

# 수치 패턴
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*\s?(?:%|퍼센트|배|초|ms|분|시간|일|줄|개|회|건|자|행|MB|KB|GB)?")
# 식별자 패턴
IDENT = re.compile(r"(?<![\w-])--?[A-Za-z][\w-]+|[A-Za-z_][A-Za-z0-9_]*(?:[./][A-Za-z0-9_*]+)+|[A-Z][A-Z0-9_]{2,}\*?|[a-z]+_[a-z0-9_]+")
# 판단 표현 목록
JUDGE = ("향상", "개선", "절감", "저하", "악화", "엄격", "완화", "강화", "축소", "확대", "최소화", "최대화",
         "효과", "보장", "정확도", "높이", "낮추", "늘리", "줄이", "빨라", "느려")
# 단정 표현 목록
ABSOLUTE = ("모두", "완전", "항상", "반드시", "전혀", "절대")
# 한글 어절 연속 패턴
RUN = re.compile(r"[\uac00-\ud7a3]{2,}(?: [\uac00-\ud7a3]{2,})+")
# 조사 패턴
PARTICLE = re.compile(r"(으로|에서|에게|까지|부터|보다|처럼|이나|이며|이고|을|를|이|가|은|는|의|로|에|와|과|도|만)$")
# 한글 단어 패턴
HANGUL_WORD = re.compile(r"[가-힣]{2,}")
# 최대 출력 건수
LIMIT = 12


def parts(token):
    """식별자를 구성 단위로 분리합니다."""
    return [p for p in re.split(r"[=*,·]+", token) if len(p) >= 2]


def grounded(token, ground):
    """식별자가 근거 텍스트에 존재하는지 검사합니다."""
    if token.isupper() and token.lower() in ground.lower():
        return True
    return token in ground or all(p in ground for p in parts(token))


def stem(word):
    """단어 끝의 조사를 제거합니다."""
    return PARTICLE.sub("", word)


def pairs_of(line):
    """줄 안에서 연속한 두 단어 쌍 목록을 생성합니다."""
    out = []
    # 연속 어절 순회
    for run in RUN.findall(line):
        words = [stem(w) for w in run.split(" ")]
        out += [f"{a} {b}" for a, b in zip(words, words[1:]) if len(a) >= 2 and len(b) >= 2]
    return out


def review(old, new, request="", terms=True):
    """변경 줄을 검사하여 사실 확인이 필요한 항목을 추출합니다."""
    olines, nlines = old.split("\n"), new.split("\n")
    ground = f"{old}\n{request}"
    added = []
    # 줄 단위 변경 연산 순회
    for tag, i1, i2, j1, j2 in line_opcodes(old, new):
        if tag in ("insert", "replace"):
            before = "\n".join(olines[i1:i2])
            # 추가 및 치환 줄 순회
            for j in range(j1, j2):
                if nlines[j].strip():
                    added.append((j + 1, nlines[j], before))
    known = {stem(w) for w in HANGUL_WORD.findall(ground)}
    counts = Counter()
    # 추가 줄 순회
    for _, line, _ in added:
        # 단어 쌍 순회
        for t in pairs_of(line):
            a, b = t.split(" ")
            if a not in known or b not in known:
                counts[t] += 1
    new_terms = {t for t, n in counts.items() if n >= 2} if terms else set()
    out = []
    # 대상 줄 순회
    for no, line, before in added:
        reasons = []
        nums = [n.strip() for n in NUMBER.findall(line) if len(n.strip()) >= 2]
        bad = [n for n in nums if re.sub(r"\s", "", n) not in re.sub(r"\s", "", ground)]
        if bad:
            reasons.append("근거 없는 수치 " + ", ".join(dict.fromkeys(bad)))
        idents = [t for t in IDENT.findall(line) if not grounded(t, ground)]
        if idents:
            reasons.append("근거 없는 식별자 " + ", ".join(dict.fromkeys(idents)))
        judge = [w for w in JUDGE if w in line and w not in before and w not in request]
        judge += [w for w in ABSOLUTE if w in line and w not in before]
        if judge:
            reasons.append("판단 표현 " + ", ".join(judge))
        fresh = [t for t in pairs_of(line) if t in new_terms]
        if fresh:
            reasons.append("새 용어 " + ", ".join(dict.fromkeys(fresh)))
        if reasons:
            out.append((no, "; ".join(reasons), line.strip()))
    return out


def report(items):
    """검사 결과 목록을 보고서 형식 문자열로 변환합니다."""
    if not items:
        return ""
    rows = [f"L{no} [{why}] {text[:120]}" for no, why, text in items[:LIMIT]]
    more = len(items) - LIMIT
    if more > 0:
        rows.append(f"... {more} more")
    return "check:\n" + "\n".join(rows)


if __name__ == "__main__":
    old, new = (open(p, encoding="utf-8").read() for p in sys.argv[1:3])
    request = open(sys.argv[3], encoding="utf-8").read() if len(sys.argv) > 3 else ""
    print(report(review(old, new, request)))
