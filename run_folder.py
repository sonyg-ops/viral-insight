"""0단계 — 폴더 하나를 판독해서 시트에 넣습니다.

    # 구글 인증 없이 CSV로 결과만 확인 (먼저 이걸로 검증하세요)
    python run_folder.py --folder "..\\루나앤코코\\0823" --vendor 루나앤코코 ^
        --rows "..\\실제인사이트_260823.xlsx"

    # 시트에서 후보를 읽고, 스테이징 탭에만 기록 (RD 시트는 안 건드림)
    python run_folder.py --folder "..\\루나앤코코\\0823" --vendor 루나앤코코 --sheet

    # 확정 건을 RD 시트 날짜 열에 실제로 기입
    python run_folder.py --folder "..\\루나앤코코\\0823" --vendor 루나앤코코 --sheet --commit
"""
from __future__ import annotations

import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

import config
import extract
import matcher
import sheet


def guess_target(folder: Path) -> date:
    """폴더명 '0823' → 올해 8월 23일."""
    m = re.search(r"(\d{2})(\d{2})$", folder.name)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = date.today().year
        try:
            return date(y, mo, d)
        except ValueError:
            pass
    return date.today()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True, help="스크린샷 폴더")
    ap.add_argument("--vendor", required=True, help="업체명 (시트 업체명 열과 같아야 함)")
    ap.add_argument("--date", help="데이터 기준일 YYYY-MM-DD (기본: 폴더명에서 추정)")
    ap.add_argument("--captured", help="캡처 시각 YYYY-MM-DD HH:MM (기본: 기준일 다음날 10:00)")
    ap.add_argument("--rows", help="후보 행을 읽을 로컬 xlsx (구글 인증 없이 테스트용)")
    ap.add_argument("--sheet", action="store_true", help="구글시트에서 후보를 읽고 스테이징에 기록")
    ap.add_argument("--commit", action="store_true", help="확정 건을 RD 시트 날짜 열에 기입")
    ap.add_argument("--scope", choices=["window", "day"], default="window",
                    help="day = 이 폴더가 해당 업로드일 게시물만 담고 있음 (루나앤코코 방식). "
                         "window = 추적중 전체 (업크루·굿띵투유 방식)")
    ap.add_argument("--out", default="결과.csv")
    a = ap.parse_args()

    folder = Path(a.folder)
    if not folder.is_dir():
        print(f"폴더가 없습니다: {folder}")
        return 1

    target = datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else guess_target(folder)
    captured = a.captured or f"{target.fromordinal(target.toordinal() + 1)} 10:00"

    print(f"업체={a.vendor}  기준일={target}  캡처시각={captured}")
    print(f"모델={config.MODEL}  effort={config.EFFORT}")

    # 1) 후보 행
    if a.sheet:
        cands = sheet.candidates_from_sheet(a.vendor, target, a.scope)
    elif a.rows:
        cands = sheet.candidates_from_xlsx(a.rows, a.vendor, target, a.scope)
    else:
        print("\n--rows 또는 --sheet 중 하나가 필요합니다.")
        return 1
    print(f"추적중 후보 행: {len(cands)}건  (scope={a.scope})")
    if not cands:
        print("후보가 없습니다. --vendor 값이 시트의 업체명과 정확히 같은지 확인하세요.")
        return 1

    # 2) 판독
    print("\n판독 중...")
    readings = extract.read_folder(folder, captured)
    if not readings:
        print("이미지가 없습니다.")
        return 1
    print(f"이미지 {len(readings)}장 판독 완료")

    # 3) 매칭
    matches = matcher.match_all(readings, cands, target)

    # 4) 출력
    order = {"확정": 0, "검토필요": 1, "매칭실패": 2, "판독실패": 3, "대상아님": 4}
    matches.sort(key=lambda m: (order.get(m.status, 9), m.reading.file))

    icon = {"확정": "OK ", "검토필요": "?? ", "매칭실패": "XX ",
            "판독실패": "!! ", "대상아님": "-- "}
    print("\n" + "=" * 100)
    for m in matches:
        r = m.reading
        reach = f"{r.reach:,}" if getattr(r, "reach", None) is not None else "-"
        row = f"{m.row.row}행 {m.row.업로드일}" if m.row else "-"
        print(f"{icon.get(m.status,'')}{r.file:<34} {reach:>10}  {row:<18} "
              f"{(getattr(r,'channel_name','') or '-'):<22} {(getattr(r,'banner_text','') or '')[:26]}")
        for w in m.warnings:
            print(f"      · {w}")

    counts = {k: sum(1 for m in matches if m.status == k) for k in order}
    print("=" * 100)
    print("  ".join(f"{k} {v}" for k, v in counts.items() if v))

    missing = matcher.missing_rows(matches, cands)
    if missing:
        print(f"\n미수신 {len(missing)}건 — 업체에 재요청:")
        for r in missing:
            print(f"  · {r.채널명}  ({r.업로드일} 업로드, {r.row}행)")

    # 5) 기록
    out = sheet.write_csv(matches, target, a.out)
    print(f"\nCSV 저장: {out}")

    if a.sheet:
        n = sheet.append_staging(matches, target, dry_run=False)
        print(f"스테이징 탭 기록: {n}행")
    if a.commit:
        n, filled = sheet.write_values(matches, target, dry_run=False)
        print(f"RD 시트 {matcher.date_col_for(target)}열에 기입: {n}건"
              + (f" (빈 날짜 열 {filled}칸에 직전값 복사)" if filled else ""))
    elif a.sheet:
        n, filled = sheet.write_values(matches, target, dry_run=True)
        print(f"(--commit 을 붙이면 확정 {n}건이 기입됩니다"
              + (f", 빈 날짜 열 {filled}칸 포함)" if filled else ")"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
