"""사용법: python3 ${CLAUDE_SKILL_DIR}/scripts/ledger.py record|accept <file>...

파일의 글 부분 해시를 ledger에 기록합니다.
ledger 위치는 git 공통 디렉터리이며 저장소 밖이면 ~/.claude/agy-write-ledger.json 경로를 사용합니다.
accept는 record와 동일하게 동작하며 사용자가 직접 작성한 글을 승인할 때 사용합니다.
"""
import fcntl
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textparts import digest, extract  # noqa: E402

# 기본 ledger 파일 경로
HOME_LEDGER = Path.home() / ".claude/agy-write-ledger.json"


def ledger_path(target: Path) -> Path:
    """대상 파일의 ledger 경로를 반환합니다."""
    # Git 공통 디렉터리 조회 실패 대응
    try:
        common = subprocess.run(
            ["git", "-C", str(target.parent), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(common) / "agy-write-ledger.json"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return HOME_LEDGER


def load(path: Path) -> dict:
    """ledger 파일 내용을 읽어옵니다."""
    # 파일 부재 및 JSON 파싱 오류 대응
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def record(files: list) -> None:
    """지정한 파일들의 글 부분 해시를 ledger에 기록합니다."""
    # 대상 파일 순회
    for name in files:
        target = Path(name).resolve()
        path = ledger_path(target)
        value = digest(extract(str(target), target.read_text(encoding="utf-8")))
        with open(path.with_name(path.name + ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = load(path)
            data[str(target)] = value
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        print(f"recorded {target}")


def recorded(target: Path) -> str:
    """ledger에 기록된 대상 파일의 해시를 조회합니다."""
    return load(ledger_path(target)).get(str(target), "")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("record", "accept"):
        sys.exit("ledger.py record|accept <file>...")
    record(sys.argv[2:])
