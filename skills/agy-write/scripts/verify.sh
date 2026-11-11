#!/bin/bash
# 사용법: ${CLAUDE_SKILL_DIR}/scripts/verify.sh <이전 판> <새 판>
# 문서 파일 이전 판과 새 판 기계 대조 보고
set -uo pipefail
OLD="$1"; NEW="$2"; T=$(mktemp -d)
blocks() { awk '/^```/{c=!c;next} c' "$1"; }
body()   { awk '/^```/{c=!c;next} !c && !/^\|/' "$1"; }
toks()   { grep -oE '`[^`]+`' "$1" | sort -u; }
echo "## 코드 블록"
if diff <(blocks "$OLD") <(blocks "$NEW") > "$T/blk"; then echo "동일합니다."; else echo "차이가 있습니다:"; head -40 "$T/blk"; fi
echo; echo "## 표 행 수"; echo "이전 판 $(grep -c '^|' "$OLD") / 새 판 $(grep -c '^|' "$NEW")"
echo; echo "## 백틱 식별자 집합 차이"
toks "$OLD" > "$T/o"; toks "$NEW" > "$T/n"
echo "[이전 판에만]"; comm -23 "$T/o" "$T/n"; echo "[새 판에만]"; comm -13 "$T/o" "$T/n"
echo; echo "## 금지 표현 (행 번호)"
echo "[긴 하이픈 및 이모지]"; perl -CSD -ne 'print "$.: $_" if /\x{2014}|[\x{1F300}-\x{1FAFF}\x{2705}\x{274C}]/' "$NEW" | cut -c1-120 | grep . || echo "없습니다."
echo "[음차 및 직역 의심 (지정 패턴 검사)]"; grep -nE '하우투|처음부터 끝까지' "$NEW" | cut -c1-120 || echo "없습니다."
echo "[이력성 서술 의심]"; grep -nE '과거|예전|바로잡|지적|이전 개정|변경하였|수정하였' "$NEW" | cut -c1-120 || echo "없습니다."
echo "[절 소개 문장]"; grep -nE '^이 절은|^본 절은' "$NEW" | cut -c1-120 || echo "없습니다."
echo; echo "## 분량과 쉼표"
printf '%-8s %6s %8s %10s %10s\n' 판 줄수 바이트 본문쉼표 표쉼표
for f in "$OLD" "$NEW"; do printf '%-8s %6s %8s %10s %10s\n' "$( [ "$f" = "$OLD" ] && echo 이전판 || echo 새판 )" "$(wc -l < "$f" | tr -d ' ')" "$(wc -c < "$f" | tr -d ' ')" "$(body "$f" | grep -o ',' | wc -l | tr -d ' ')" "$(grep '^|' "$f" | grep -o ',' | wc -l | tr -d ' ')"; done
echo; echo "## 변경된 줄 (앞 60자)"
diff "$OLD" "$NEW" | grep '^[<>]' | cut -c1-80 | head -40
rm -rf "$T"
