"""UserPromptSubmit 훅 스크립트입니다.

assets/messages.json의 prompt_context 문구를 additionalContext로 주입합니다.

사용법:
    python3 ${CLAUDE_SKILL_DIR}/scripts/hooks/prompt_context.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    """추가 컨텍스트를 표준 출력으로 전달합니다."""
    messages = json.loads((ROOT / "assets/messages.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": messages["prompt_context"],
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
