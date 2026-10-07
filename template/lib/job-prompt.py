"""명령 메타데이터를 제외한 예약 업무 본문만 출력한다."""
from pathlib import Path
import sys


def render(path, today):
    text = Path(path).read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                text = "".join(lines[index + 1:])
                break
        else:
            raise ValueError("명령 머리말의 닫는 구분선이 없습니다")
    if not text.strip():
        raise ValueError("명령 본문이 비어 있습니다")
    return text.replace("$ARGUMENTS", today)


if __name__ == "__main__":
    try:
        sys.stdout.write(render(sys.argv[1], sys.argv[2]))
    except (OSError, UnicodeError, ValueError) as error:
        # 명령 본문이나 고객 데이터를 오류 알림에 포함하지 않는다.
        print(f"예약 업무 프롬프트 준비 실패: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
