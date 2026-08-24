"""판독 결과를 RD 시트의 행에 배정합니다.

검증(2026-08-24, 52장)에서 확인된 순서를 그대로 씁니다:
  1순위 채널명   — 유일하게 신뢰할 수 있었던 키
  2순위 게시일
  3순위 배너문구 — 시트의 소재명·캡션이 채널 간에 밀려 기록된 행이 있어 보조로만 씁니다
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

import config


# ── 정규화 ───────────────────────────────────────────────────

def norm_channel(s: str | None) -> str:
    """Ufo__yellow / ufo_yellow / Ufo__Yellow → 'ufoyellow'

    밑줄 개수와 대소문자 차이는 흡수하되, 글자 자체는 보존합니다.
    (Ufo__RED 와 Ufo__yellow 는 여전히 구분됩니다.)
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    s = s.lstrip("@")
    return re.sub(r"[^0-9a-z가-힣]+", "", s)


def norm_text(s: str | None) -> str:
    """배너문구 비교용. 공백·마침표·따옴표·이모지를 제거합니다."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    return re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]+", "", s)


def banner_score(read_banner: str | None, sheet_소재명: str | None,
                 sheet_캡션: str | None) -> float:
    """0.0 ~ 1.0. 소재명과 캡션 중 더 잘 맞는 쪽을 씁니다."""
    a = norm_text(read_banner)
    if not a:
        return 0.0
    best = 0.0
    for cand in (sheet_소재명, sheet_캡션):
        b = norm_text(cand)
        if not b:
            continue
        if a in b or b in a:
            best = max(best, 1.0)
            continue
        # 부분일치가 안 되면 유사도. 앞/뒤 조각 일치도 반영합니다.
        ratio = SequenceMatcher(None, a, b).ratio()
        head = 1.0 if len(a) >= 6 and a[:6] in b else 0.0
        tail = 1.0 if len(a) >= 6 and a[-6:] in b else 0.0
        best = max(best, max(ratio, 0.55 * (head + tail) / 2 + ratio * 0.5))
    return min(1.0, best)


# ── 후보 행 ──────────────────────────────────────────────────

@dataclass
class Row:
    """RD 시트의 한 행."""
    row: int
    업로드일: str          # 'YYYY-MM-DD'
    채널명: str
    소재명: str = ""
    캡션: str = ""
    업체명: str = ""
    비용: float | None = None
    prev_value: int | None = None   # 직전 날짜 열의 값
    current_value: int | None = None  # 대상 날짜 열에 이미 들어있는 값
    last_value: int | None = None    # 대상일 이전 마지막으로 측정된 값
    last_col: int | None = None      # 그 값이 있던 열 번호


@dataclass
class Match:
    reading: object
    row: Row | None = None
    score: float = 0.0
    runner_up: float = 0.0
    warnings: list[str] = field(default_factory=list)
    status: str = "미확정"     # 확정 / 검토필요 / 매칭실패 / 판독실패 / 대상아님

    @property
    def confidence(self) -> str:
        if self.status != "확정":
            return "-"
        gap = self.score - self.runner_up
        if gap >= 40:
            return "높음"
        if gap >= config.AMBIGUOUS_MARGIN:
            return "보통"
        return "낮음"


def date_col_for(target: date) -> int:
    """대상 날짜의 열 번호. P열=FIRST_DATE 기준 하루 1열."""
    base = datetime.strptime(config.FIRST_DATE, "%Y-%m-%d").date()
    return config.FIRST_DATE_COL + (target - base).days


def match_one(reading, candidates: list[Row], target: date) -> Match:
    m = Match(reading=reading)

    if not getattr(reading, "ok", False):
        m.status = "판독실패"
        m.warnings.append(reading.error or "알 수 없는 오류")
        return m

    if not reading.is_insight_screen:
        m.status = "대상아님"
        m.warnings.append("인사이트 화면이 아닙니다 (피드/그래프/프로필 등)")
        return m

    if reading.reach is None:
        m.status = "판독실패"
        if reading.views is not None:
            m.warnings.append(
                f"도달값이 화면에 없습니다. 조회={reading.views:,} 만 읽혔습니다. "
                "도달(조회한 사람)이 보이는 화면을 다시 받아야 합니다")
        else:
            m.warnings.append("숫자를 읽을 수 없습니다: " + (reading.notes or ""))
        return m

    # ── 점수 계산 ────────────────────────────────────────────
    rc = norm_channel(reading.channel_name)
    scored: list[tuple[float, Row, bool]] = []   # (점수, 행, 채널명이 근사일치인지)
    for row in candidates:
        s = 0.0
        fuzzy = False
        sc = norm_channel(row.채널명)
        if rc and sc:
            if rc == sc:
                s += config.SCORE_CHANNEL_EXACT
            else:
                # laugh.34 vs laugh.35 처럼 업체가 라벨을 잘못 적은 경우를 살립니다.
                ratio = SequenceMatcher(None, rc, sc).ratio()
                if ratio >= config.CHANNEL_NEAR_RATIO:
                    s += config.SCORE_CHANNEL_NEAR * ratio
                    fuzzy = True
        if reading.post_date and reading.post_date == row.업로드일:
            s += config.SCORE_DATE_MATCH
        s += config.SCORE_BANNER_MAX * banner_score(
            reading.banner_text, row.소재명, row.캡션)
        if s > 0:
            scored.append((s, row, fuzzy))

    scored.sort(key=lambda t: -t[0])
    if not scored or scored[0][0] < config.MIN_SCORE:
        m.status = "매칭실패"
        m.score = scored[0][0] if scored else 0.0
        m.warnings.append(
            f"시트에서 해당 행을 못 찾았습니다 (채널명='{reading.channel_name}', "
            f"배너='{reading.banner_text}')")
        if scored:
            top = scored[0][1]
            m.warnings.append(
                f"가장 가까운 후보: {top.row}행 {top.채널명} ({top.업로드일}) — 점수 {scored[0][0]:.0f}")
        return m

    m.score, m.row, fuzzy = scored[0]
    m.runner_up = scored[1][0] if len(scored) > 1 else 0.0
    m.status = "확정"

    if fuzzy:
        m.status = "검토필요"
        m.warnings.append(
            f"채널명이 시트와 다릅니다: 판독 '{reading.channel_name}' vs 시트 '{m.row.채널명}'. "
            "배너문구로 이 행이라고 판단했습니다")

    # 동점에 가까우면 사람이 봐야 합니다 (월요일 같은 채널 다건 케이스)
    if m.score - m.runner_up < config.AMBIGUOUS_MARGIN:
        m.status = "검토필요"
        others = ", ".join(f"{r.업로드일}({r.row}행)" for _s, r, _f in scored[1:3])
        m.warnings.append(f"후보가 여럿입니다. 1순위 {m.row.업로드일}({m.row.row}행) vs {others}")

    # ── 검증 규칙 ────────────────────────────────────────────
    if m.row.prev_value is not None and reading.reach < m.row.prev_value:
        m.status = "검토필요"
        m.warnings.append(
            f"전일값({m.row.prev_value:,})보다 작습니다({reading.reach:,}). "
            "누적값은 줄어들 수 없습니다")

    if m.row.current_value is not None:
        if m.row.current_value != reading.reach:
            # 이미 다른 값이 들어있으면 절대 자동으로 덮어쓰지 않습니다.
            m.status = "검토필요"
            m.warnings.append(
                f"이미 값({m.row.current_value:,})이 있는데 판독값은 {reading.reach:,} 입니다. "
                "덮어쓰려면 직접 지정해 주세요")
        else:
            m.warnings.append("이미 같은 값이 들어있습니다 (중복 수신)")

    if reading.views is not None and m.row.current_value == reading.views:
        m.status = "검토필요"
        m.warnings.append(
            f"시트의 기존값이 '조회'({reading.views:,})와 같습니다. "
            f"도달은 {reading.reach:,} 입니다 — 지표 혼동 의심")

    if reading.reach_is_rounded:
        m.warnings.append(
            f"축약값입니다 (오차 ±500). 원본 표기에서 {reading.reach:,} 로 환산했습니다")

    if reading.platform == "tiktok":
        m.warnings.append("틱톡입니다. '총 시청자 수'를 도달로 읽었고 K 단위 반올림입니다")

    if reading.banner_partial:
        m.warnings.append("배너문구가 잘려 일부만 읽혔습니다")

    if not rc:
        m.warnings.append("채널명을 못 읽어 배너문구만으로 매칭했습니다")

    return m


def match_all(readings, candidates: list[Row], target: date) -> list[Match]:
    """전체 매칭 후 같은 행에 두 건이 배정된 경우를 정리합니다."""
    matches = [match_one(r, candidates, target) for r in readings]

    by_row: dict[int, list[Match]] = {}
    for m in matches:
        if m.row is not None:
            by_row.setdefault(m.row.row, []).append(m)

    for row_no, group in by_row.items():
        if len(group) > 1:
            group.sort(key=lambda m: -m.score)
            for m in group[1:]:
                m.status = "검토필요"
                m.warnings.append(
                    f"{row_no}행에 다른 이미지({group[0].reading.file})도 배정됐습니다. "
                    "둘 중 하나는 다른 행입니다")
    return matches


def missing_rows(matches: list[Match], candidates: list[Row]) -> list[Row]:
    """캡처를 못 받은 행 = 재요청 대상. 업로드일 최신순."""
    hit = {m.row.row for m in matches if m.row is not None}
    out = [r for r in candidates if r.row not in hit and r.current_value is None]
    out.sort(key=lambda r: (r.업로드일, r.채널명), reverse=True)
    return out
