# agy-write

## 개요
Claude Code가 파일 안의 글(주석, docstring, 한글 문자열, 문서 본문)을 직접 쓰지 않고 agy CLI(Gemini)에 비대화형으로 위임합니다. 결과를 기계 대조로 검증하고 코드가 바뀌면 원본으로 복원합니다.

## 구성 요소
- `skills/agy-write` (스킬 본문 SKILL.md, scripts, assets)
- `hooks/hooks.json` (UserPromptSubmit 훅이 안내 문구를 주입하고 PreToolUse Bash 훅 commit_gate.py가 커밋을 차단함)
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

## 사전 준비
Claude Code, python3, git, agy CLI 설치 및 로그인이 필요하며 agy 명령이 PATH에서 실행되어야 합니다. 기본 모델은 gemini-3.8-flash-medium이고 계정에서 쓸 수 없으면 AGY_MODEL로 다른 모델을 지정합니다.

## 설치
로컬 폴더에서 설치할 때는 다음 명령을 실행합니다.

```bash
claude plugin marketplace add <이 폴더 경로>
claude plugin install agy-write@agy-write
```

Git 저장소에 올린 경우 `claude plugin marketplace add <owner>/<repo>` 형식으로 추가합니다. 설치 후 Claude Code를 다시 시작합니다.

## 사용 방법
문서 작성이나 수정을 요청하면 스킬이 활성화됩니다. 직접 실행할 때는 다음 형식을 사용합니다.

```bash
python3 <스킬 폴더>/scripts/annotate.py FILE[:LOCATION][=REQUEST]...
```

LOCATION은 줄 범위나 함수 이름이며 REQUEST는 코드에 없는 사실 정보입니다.

## 환경 변수
- `AGY_MODEL`: 모든 파일에 쓸 모델
- `AGY_WORK`: 프롬프트·결과·백업 저장 폴더 (없으면 임시 폴더)
- `AGY_RETRIES`: 기본 2
- `AGY_TIMEOUT`: 기본 660초

## 커밋 차단
이번 커밋에 들어갈 글이 ledger 기록과 다르면 커밋을 막고 파일:줄 범위를 안내합니다. ledger 위치는 git 공통 디렉터리의 `agy-write-ledger.json`이고 저장소 밖이면 `~/.claude/agy-write-ledger.json`입니다. 사용자가 직접 쓴 글은 차단 메시지에 안내되는 `ledger.py accept <파일>` 명령으로 승인합니다. 계속 제외할 경로는 `.git/info/agy-write-ignore` 파일에 적으며 `/`로 끝나는 항목은 폴더이고 나머지는 파일 이름 패턴입니다. 훅은 플러그인을 켠 모든 프로젝트의 git commit에 적용됩니다.

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

## 기존 수동 설치 사용자 안내
순서는 플러그인 설치 후 정리입니다. 정리 대상은 두 가지로 `~/.claude/skills/agy-write` 폴더와 `~/.claude/settings.json`의 `hooks` 항목 두 개입니다. 두 항목을 남겨 두면 안내 문구 주입과 커밋 검사가 두 번 실행됩니다.

1. `~/.claude/skills/agy-write` 폴더를 지웁니다.

```bash
rm -rf ~/.claude/skills/agy-write
```

2. 편집기로 `~/.claude/settings.json`을 열어 해당 항목만 지웁니다. 지울 항목은 `hooks.UserPromptSubmit` 안의 `command` 값에 `skills/agy-write/scripts/hooks/prompt_context.py`가 들어 있는 항목과 `hooks.PreToolUse` 안의 `matcher`가 `Bash`이고 `command` 값에 `skills/agy-write/scripts/hooks/commit_gate.py`가 들어 있는 항목입니다. 같은 배열에 다른 훅이 있으면 그 훅은 남깁니다.

3. 정리 후 다음 명령의 실행 결과가 비어 있으면 정리가 끝난 것입니다.

```bash
grep -n "skills/agy-write" ~/.claude/settings.json
```

4. 정리 후 Claude Code를 다시 시작합니다.
