"""RD 시트 읽기/쓰기.

구글 인증이 없어도 로컬 CSV/XLSX 스냅샷으로 후보 행을 만들 수 있습니다.
(먼저 CSV로 검증하고, 자동화가 확인되면 --sheet 로 바꾸는 순서를 권합니다.)
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import config
from matcher import Row, date_col_for


def _parse_date(v) -> str:
    """'2026. 8. 22.' / '2026-08-22' / date → 'YYYY-MM-DD'"""
    if v is None or v == "":
        return ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"^(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return s


def _to_int(v) -> int | None:
    if v is None:
        return None
    s = re.sub(r"[^0-9-]", "", str(v))
    if s in ("", "-"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


# ── 로컬 스냅샷에서 후보 만들기 ────────────────────────────────

def candidates_from_xlsx(path: str | Path, vendor: str, target: date,
                         scope: str = "window") -> list[Row]:
    """실제인사이트_*.xlsx 처럼 A~N 열만 있는 파일도 받습니다.

    날짜 열이 없으면 prev_value / current_value 는 None 이 됩니다.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(path)
    shared = []
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    except KeyError:
        pass

    sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    grid: dict[int, dict[int, str]] = {}
    for tr in sheet.iter(NS + "row"):
        rn = int(tr.get("r"))
        cells: dict[int, str] = {}
        for c in tr.findall(NS + "c"):
            ref = c.get("r") or ""
            col = _col_index(re.match(r"[A-Z]+", ref).group(0)) if re.match(r"[A-Z]+", ref) else 0
            v = c.find(NS + "v")
            t = c.get("t")
            if t == "s" and v is not None:
                cells[col] = shared[int(v.text)]
            elif v is not None:
                cells[col] = v.text
        grid[rn] = cells

    rows: list[Row] = []
    lo = target if scope == "day" else target - timedelta(days=config.TRACKING_WINDOW_DAYS)
    hi = target if scope == "day" else target
    for rn, cells in grid.items():
        if rn <= config.HEADER_ROW:
            continue
        if (cells.get(config.COL["업체명"], "") or "").strip() != vendor:
            continue
        up = _parse_date(cells.get(config.COL["업로드일"]))
        if not up:
            continue
        try:
            upd = datetime.strptime(up, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (lo <= upd <= target):
            continue
        rows.append(Row(
            row=rn,
            업로드일=up,
            채널명=(cells.get(config.COL["채널명"]) or "").strip(),
            소재명=(cells.get(config.COL["소재명"]) or "").strip(),
            캡션=(cells.get(config.COL["캡션"]) or "").strip(),
            업체명=vendor,
            비용=_to_int(cells.get(config.COL["비용"])),
        ))
    return rows


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


# ── 구글시트 ─────────────────────────────────────────────────

def _gs():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        config.GOOGLE_CREDENTIALS,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds).open_by_key(config.SHEET_ID)


def candidates_from_sheet(vendor: str, target: date, scope: str = "window") -> list[Row]:
    ws = _gs().worksheet(config.TAB_RD)
    grid = ws.get_all_values()
    tcol = date_col_for(target)
    pcol = tcol - 1
    lo = target if scope == "day" else target - timedelta(days=config.TRACKING_WINDOW_DAYS)

    rows: list[Row] = []
    for i, r in enumerate(grid[config.HEADER_ROW:], start=config.HEADER_ROW + 1):
        def cell(c: int) -> str:
            return r[c - 1] if len(r) >= c else ""

        if cell(config.COL["업체명"]).strip() != vendor:
            continue
        if config.CHANNEL_FILTER and config.CHANNEL_FILTER not in cell(config.COL["채널분류"]):
            continue
        up = _parse_date(cell(config.COL["업로드일"]))
        if not up:
            continue
        try:
            upd = datetime.strptime(up, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (lo <= upd <= target):
            continue

        # 대상일 이전 마지막 측정값 (빈 날짜 열 채우기에 씁니다)
        last_v = last_c = None
        for c in range(tcol - 1, config.FIRST_DATE_COL - 1, -1):
            v = _to_int(cell(c))
            if v is not None:
                last_v, last_c = v, c
                break

        rows.append(Row(
            row=i,
            업로드일=up,
            채널명=cell(config.COL["채널명"]).strip(),
            소재명=cell(config.COL["소재명"]).strip(),
            캡션=cell(config.COL["캡션"]).strip(),
            업체명=vendor,
            비용=_to_int(cell(config.COL["비용"])),
            prev_value=_to_int(cell(pcol)),
            current_value=_to_int(cell(tcol)),
            last_value=last_v,
            last_col=last_c,
        ))
    return rows


def write_values(matches, target: date, dry_run: bool = True,
                 fill_gaps: bool = True) -> tuple[int, int]:
    """확정된 매칭을 대상 날짜 열에 씁니다. 다른 열은 건드리지 않습니다.

    fill_gaps=True 면 월요일처럼 측정을 건너뛴 중간 날짜 열에
    직전 측정값을 복사합니다. 0을 넣으면 증분값이 왜곡되기 때문입니다.
    게시물이 아직 없던 날짜(업로드일 이전)는 비워 둡니다.

    반환: (기입한 건수, 빈칸 채운 칸수)
    """
    todo = [m for m in matches if m.status == "확정" and m.row is not None]
    if not todo:
        return 0, 0

    tcol = date_col_for(target)
    base = datetime.strptime(config.FIRST_DATE, "%Y-%m-%d").date()
    plan: list[tuple[int, int, int]] = []   # (행, 열, 값)
    filled = 0

    for m in todo:
        row = m.row
        plan.append((row.row, tcol, m.reading.reach))
        if not fill_gaps or row.last_value is None or row.last_col is None:
            continue
        try:
            upd = datetime.strptime(row.업로드일, "%Y-%m-%d").date()
        except ValueError:
            continue
        for c in range(row.last_col + 1, tcol):
            col_date = base + timedelta(days=c - config.FIRST_DATE_COL)
            if col_date < upd:          # 게시물이 아직 없던 날
                continue
            plan.append((row.row, c, row.last_value))
            filled += 1

    if dry_run:
        return len(todo), filled

    import gspread
    ws = _gs().worksheet(config.TAB_RD)
    ws.update_cells([gspread.Cell(r, c, v) for r, c, v in plan],
                    value_input_option="USER_ENTERED")
    return len(todo), filled


def append_staging(matches, target: date, dry_run: bool = True) -> int:
    """검토용 스테이징 탭에 전체 판독 이력을 남깁니다."""
    header = ["수집일", "업체명", "파일명", "상태", "신뢰도", "채널명(판독)", "배너문구(판독)",
              "도달", "조회", "게시일(판독)", "매칭행", "시트채널명", "시트업로드일", "경고"]
    body = []
    for m in matches:
        r = m.reading
        body.append([
            target.isoformat(),
            (m.row.업체명 if m.row else ""),
            r.file,
            m.status,
            m.confidence,
            getattr(r, "channel_name", "") or "",
            getattr(r, "banner_text", "") or "",
            getattr(r, "reach", None) if getattr(r, "reach", None) is not None else "",
            getattr(r, "views", None) if getattr(r, "views", None) is not None else "",
            getattr(r, "post_date", "") or "",
            m.row.row if m.row else "",
            m.row.채널명 if m.row else "",
            m.row.업로드일 if m.row else "",
            " / ".join(m.warnings),
        ])
    if dry_run:
        return len(body)

    import gspread
    sh = _gs()
    try:
        ws = sh.worksheet(config.TAB_STAGING)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(config.TAB_STAGING, rows=2000, cols=len(header))
        ws.append_row(header, value_input_option="USER_ENTERED")
    if not ws.get_all_values():
        ws.append_row(header, value_input_option="USER_ENTERED")
    ws.append_rows(body, value_input_option="USER_ENTERED")
    return len(body)


def write_csv(matches, target: date, out: str | Path) -> Path:
    """구글 인증 없이 결과를 확인할 때 씁니다."""
    out = Path(out)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["수집일", "파일명", "상태", "신뢰도", "채널명(판독)", "배너문구(판독)",
                    "도달", "조회", "게시일(판독)", "매칭행", "시트채널명", "시트업로드일", "경고"])
        for m in matches:
            r = m.reading
            w.writerow([
                target.isoformat(), r.file, m.status, m.confidence,
                getattr(r, "channel_name", "") or "",
                getattr(r, "banner_text", "") or "",
                getattr(r, "reach", "") if getattr(r, "reach", None) is not None else "",
                getattr(r, "views", "") if getattr(r, "views", None) is not None else "",
                getattr(r, "post_date", "") or "",
                m.row.row if m.row else "",
                m.row.채널명 if m.row else "",
                m.row.업로드일 if m.row else "",
                " / ".join(m.warnings),
            ])
    return out
