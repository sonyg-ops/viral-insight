"""다운로드한 서비스 계정 JSON → Streamlit Secrets 에 붙여넣을 TOML.

private_key 안의 \\n 을 직접 옮기다가 틀리는 일을 막아줍니다.

    python secrets_만들기.py "C:\\Users\\sonyg\\Downloads\\lalasweet-bingwa-abc123.json"

경로를 안 주면 다운로드 폴더에서 가장 최근 서비스 계정 JSON 을 찾습니다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NEEDED = ["type", "project_id", "private_key_id", "private_key",
          "client_email", "client_id", "token_uri"]


def find_json() -> Path | None:
    dl = Path.home() / "Downloads"
    if not dl.is_dir():
        return None
    best, best_t = None, -1.0
    for p in dl.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("type") == "service_account":
            t = p.stat().st_mtime
            if t > best_t:
                best, best_t = p, t
    return best


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1].strip('"'))
    else:
        path = find_json()
        if path is None:
            print("다운로드 폴더에서 서비스 계정 JSON 을 못 찾았습니다.")
            print('사용법: python secrets_만들기.py "JSON파일경로"')
            return 1
        print(f"찾은 파일: {path}\n")

    if not path.is_file():
        print(f"파일이 없습니다: {path}")
        return 1

    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"JSON 을 읽을 수 없습니다: {e}")
        return 1

    if d.get("type") != "service_account":
        print("서비스 계정 키 파일이 아닙니다. Google Cloud 에서 받은 JSON 이 맞는지 확인하세요.")
        return 1

    missing = [k for k in NEEDED if not d.get(k)]
    if missing:
        print(f"필요한 항목이 빠져 있습니다: {', '.join(missing)}")
        return 1

    key = d["private_key"].replace("\\n", "\n").replace("\n", "\\n")

    print("=" * 70)
    print("아래를 통째로 복사해서 Streamlit Secrets 맨 아래에 붙여넣으세요.")
    print("=" * 70)
    print()
    print("[google_service_account]")
    for k in NEEDED:
        v = key if k == "private_key" else d[k]
        print(f'{k} = "{v}"')
    print()
    print("=" * 70)
    print(f"\n▶ 시트 공유할 이메일 (편집자로 추가):\n\n   {d['client_email']}\n")
    print("이 이메일을 콘텐츠RD 시트 [공유] 에 편집자로 추가하지 않으면")
    print("사이트가 시트를 찾지 못합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
