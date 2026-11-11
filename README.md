# agy-write

## 개요
Claude Code가 파일 안의 글(주석, docstring, 한글 문자열, 문서 본문) 작성을 agy CLI에 비대화형으로 위임합니다. 기계 대조로 결과를 검증하여 코드가 변경되면 원본으로 복원합니다.

## 구성 요소
- `skills/agy-write` (스킬 본문 `SKILL.md` 및 보조 파일 포함)
- `hooks/hooks.json` (안내 문구를 주입하는 UserPromptSubmit 훅 및 커밋을 차단하는 PreToolUse Bash 훅 포함)
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

## 사전 준비
Claude Code와 python3 및 git과 agy CLI 설치 후 로그인이 필요합니다. `agy` 명령이 PATH 환경 변수에서 실행 가능해야 합니다. 기본 모델은 `gemini-3.8-flash-medium`이며 계정에서 사용할 수 없으면 `AGY_MODEL` 환경 변수로 다른 모델을 지정합니다.

## 설치
Git 저장소에서 설치할 때는 다음 명령을 실행합니다.

```bash
claude plugin marketplace add cwj0666/agy-write-plugin
claude plugin install agy-write@agy-write
```

로컬 디렉터리에서 설치할 때는 다음 명령을 실행합니다.

```bash
claude plugin marketplace add <이 폴더 경로>
claude plugin install agy-write@agy-write
```

설치 후 Claude Code를 다시 시작합니다.

## 사용 방법
문서 작성이나 수정을 요청하면 스킬이 활성화됩니다. 직접 실행할 때는 다음 형식을 사용합니다.

```bash
python3 <스킬 폴더>/scripts/annotate.py FILE[:LOCATION][=REQUEST]...
```

LOCATION은 줄 범위나 함수 이름이며 REQUEST는 코드에 없는 사실 정보입니다.

## 환경 변수
- `AGY_MODEL`: 사용할 모델 지정
- `AGY_WORK`: 프롬프트, 결과, 백업 저장 폴더 (미지정 시 임시 폴더 사용)
- `AGY_RETRIES`: 재시도 횟수 (기본값: 2)
- `AGY_TIMEOUT`: 제한 시간 (기본값: 660초)

## 커밋 차단
커밋 대상 텍스트가 ledger 기록과 다르면 커밋을 차단하고 파일과 줄 범위를 안내합니다. ledger 경로는 git 공통 디렉터리의 `agy-write-ledger.json`이며 저장소 외부에서는 `~/.claude/agy-write-ledger.json`입니다. 직접 작성한 글은 차단 메시지에 안내되는 `ledger.py accept <파일>` 명령으로 승인합니다. 제외할 경로는 `.git/info/agy-write-ignore` 파일에 지정합니다. `/`로 끝나는 항목은 디렉터리이며 나머지는 파일 이름 패턴입니다. 훅은 플러그인이 켜진 모든 프로젝트의 git commit에 적용됩니다.

## 업데이트와 제거
업데이트할 때는 다음 명령을 실행합니다.

```bash
claude plugin marketplace update agy-write
claude plugin update agy-write@agy-write
```

일시 중지할 때는 다음 명령을 실행합니다.

```bash
claude plugin disable agy-write@agy-write
```

제거할 때는 다음 명령을 실행합니다.

```bash
claude plugin uninstall agy-write@agy-write
```

## 기존 수동 설치 환경 정리
플러그인을 설치한 후 수동 설치 항목을 정리합니다. 정리 대상은 `~/.claude/skills/agy-write` 폴더와 `~/.claude/settings.json`의 훅 항목 2개입니다. 두 항목을 유지하면 안내 문구 주입과 커밋 검사가 중복 실행됩니다.

1. `~/.claude/skills/agy-write` 폴더를 삭제합니다.

```bash
rm -rf ~/.claude/skills/agy-write
```

2. `~/.claude/settings.json` 파일을 열어 해당 항목을 삭제합니다. 삭제할 대상은 `hooks.UserPromptSubmit` 안의 `command` 값에 `skills/agy-write/scripts/hooks/prompt_context.py`가 들어 있는 항목과 `hooks.PreToolUse` 안의 `matcher`가 `Bash`이고 `command` 값에 `skills/agy-write/scripts/hooks/commit_gate.py`가 들어 있는 항목입니다. 같은 배열의 다른 훅 항목은 유지합니다.

3. 다음 명령을 실행하여 결과가 비어 있는지 확인합니다.

```bash
grep -n "skills/agy-write" ~/.claude/settings.json
```

4. 정리 후 Claude Code를 다시 시작합니다.
