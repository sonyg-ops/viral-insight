"""API 키 없이 매칭 엔진만 검증합니다.

2026-08-24에 사람이 직접 판독한 45장의 결과를 넣고,
matcher 가 실제인사이트_260823.xlsx 의 어느 행으로 배정하는지 확인합니다.
기대 행의 도달값과 일치하면 통과입니다.

    python selftest.py
"""
from __future__ import annotations

import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from datetime import date
from pathlib import Path

import matcher
import sheet

XLSX = Path(__file__).resolve().parent.parent / "실제인사이트_260823.xlsx"


class R:
    """extract.Reading 과 같은 필드만 갖는 가벼운 대역."""

    def __init__(self, file, channel, banner, reach, views=None, post_date=None,
                 rounded=False, platform="instagram"):
        self.file, self.ok, self.error = file, True, ""
        self.is_insight_screen = True
        self.platform = platform
        self.channel_name = channel
        self.banner_text = banner
        self.banner_partial = False
        self.reach, self.views = reach, views
        self.reach_label = "조회한 사람"
        self.reach_is_rounded = rounded
        self.views_is_rounded = False
        self.post_date, self.post_date_source = post_date, "absolute" if post_date else None
        self.notes = ""


# (업체, 기준일, scope, [ (Reading, 기대 도달값) ])
CASES = [
    ("루나앤코코", date(2026, 8, 23), "day", [
        (R("0823-8282_humor.png", "8282_humor", "팬들이 말려서 결국 먹방 중단한 카리나 ㅠㅠ", 35289, 46837), 35289),
        (R("0823-grape_paper.png", "grape__paper", "카리나 소신 발언", 31186, 39994), 31186),
        (R("0823-hana.tving.png", "hana.tving", "사랑스러움의 의인화", 27296, 35747), 27296),
        (R("0823-luna.humor.png", "luna.humor", "나 선정 제일 웃긴 아이돌 카리나", 71704, 85351), 71704),
        (R("0823-malangping_zzal.png", "malangping_zzal", "ㄹㅇ 충격적인 에스파 카리나 근황 헐", 71767, 87423), 71767),
        (R("0823-mango_paper.png", "mango__paper", "카리나가 입으면 다 품절되는 진짜 이유", 27777, 35549), 27777),
        (R("0823-nato.healing.png", "nato.healing", "나 카리나가 왜 성격 좋다하는지 알 것 같음", 37728, 53836), 37728),
        (R("0823-orange_funny.png", "orange__funny", "언니 조심해 주세요", 23866, 30740), 23866),
        (R("0823-pink_fun_diary.png", "pink_fun_diary", "상위 0.1% 예쁜 여자들의 미인계", 79654, 101845), 79654),
        (R("0823-shashaping_humor.png", "shashaping_humor", "나는 카리나처럼 못 살 거 같다", 39151, 53247), 39151),
        (R("0823-tteokbokki__zip.png", "tteokbokki__zip", "ㅘ,, 이거 카리나가 다 유행시킴", 143895, 180191), 143895),
    ]),
    ("루나앤코코", date(2026, 8, 22), "day", [
        (R("0822-8282_humor.png", "8282_humor", "카리나 다이어트 비법", 25467, 37897), 25467),
        (R("0822-green_fun_diary.png", "green_fun_diary", "지젤 10kg 빠진 이유", 78564, 96229), 78564),
        (R("0822-luna.daily.png", "luna.daily__", "찰진 지젤 영어 발음", 56337, 71009), 56337),
        (R("0822-luna.humor.png", "luna.humor", "일본 귀족출신 강력하게 의심받는 여돌ㄷㄷ", 72405, 89152), 72405),
        (R("0822-mango_paper.png", "mango__paper", "대답만으로 부내 나는 지젤", 23226, 35156), 23226),
        (R("0822-nato.healing.png", "nato.healing", "끝이 없는 지젤의 일본인 모먼트 모음.zip", 41081, 54905), 41081),
        (R("0822-shashaping_humor.png", "shashaping_humor", "카리나가 입으면 다 품절되는 진짜 이유", 41383, 55525), 41383),
        (R("0822-tree.zzal.png", "tree.zzal", "윈터보다 더 마른 에스파 지젤 근황", 71080, 87578), 71080),
        (R("0822-tteokbokki__zip.png", "tteokbokki__zip", "실시간 지젤 일본인같다고(?) 난리난 이유", 128482, 160634), 128482),
        # 파일명은 peach_paper 인데 시트에는 grape__paper 로 기록된 건 → 매칭 실패가 정상
        (R("0822-peach_paper.png", "peach_paper", "대답만으로 부내 나는 지젤", 21830, 32612), None),
    ]),
    ("루나앤코코", date(2026, 8, 21), "day", [
        (R("0821-grape_paper.png", "grape__paper", "은근 따라해본 사람 많다는 레전드 클럽 춤 ㅋㅋ", 18522, 26839), 18522),
        (R("0821-jolly_humor.png", "jolly__humor", "전국민 다이어트 시킨 15년전 전설의 춤 ㄷㄷ", 52881, 68724), 52881),
        (R("0821-luna.besty.png", "luna.besty", "정말 묘하게 도화살 있는 것 같다는 닥터후 레전드 모음", 52625, 68272), 52625),
        (R("0821-luna.humor.png", "luna.humor", "챌린지 하다가 진심 빡친 500만 틱톡커 ㅋㅋ", 75098, 92415), 75098),
        (R("0821-nato.pick.png", "nato.pick", "갈때까지 가버린 15년도 유행 춤 근황.. ㄷㄷ", 28851, 36245), 28851),
        (R("0821-posilping_humor.png", "posilping_humor", "현시각 초딩들한테 아이브보다 더 난리라는 유튜버 정체", 43179, 57899), 43179),
        (R("0821-tree.zzal.png", "tree.zzal", "외국인은 이해 못한다는 추억 영상 ㄷㄷ", 80833, 103864), 80833),
        # 시트에 8/21 tteokbokki 행이 없음 → 매칭 실패가 정상
        (R("0821-tteokbokki__zip.png", "tteokbokki__zip", "의외로 사이버 도화살 장난 아니라는 틱톡커 ㄷㄷ", 133013, 171677), None),
    ]),
    ("굿띵투유", date(2026, 8, 23), "window", [
        (R("_00.jpg", "eattt.zin", "연예계 대표 대식가라는 의외의 여돌 ㄷㄷ", 11000, 16000, rounded=True), 11000),
        (R("_01.jpg", "kutbba101", "여름 삿포로야말로 진짜인 이유 ㅋㅋㅋ", 14326, 21649), None),
        (R("_02.jpg", "kutbba101", "주부 9단도 잘 모른다는 초록 멜론 충격 실체..ㄷㄷ", 19277, 31826), None),
        (R("_03.jpg", "kutbba101", "아이돌 중 가장 부자라는 에스파의 지젤", 24818, 43303), 24818),
        (R("_04.jpg", "kutbba101", "나 지금 되게 예쁜데", 16331, None), 16331),
        (R("_05.jpg", "kutbba101", "말 끝마다 아자스 붙이는 사람들은 ㄹㅇ", 10354, None), 10354),
        (R("_06.jpg", "Sksk1sksk1", "나는 카리나처럼 못 살 거 같다..", 22000, None, rounded=True), 22000),
        (R("_07.jpg", "Pangpang_one_", "지젤 영어 발음에 치이는 영상", 14000, None, rounded=True), 14000),
        (R("_08.jpg", "time_holy", "포켓몬카드 238억? 학부모 통장 털리는 유행 ㄷㄷ", 20562, None), 20562),
        (R("_09.jpg", "time_holy", "수상할 정도로 주위에 미녀가 몰린다는 닥터후 ㅋㅋ", 40327, None), 40327),
        (R("_10.jpg", "hoho_cutie_", "요즘 초딩들한테 대통령보다 영향력 세다는 유튜버 ㄷㄷ", 13846, None,
            post_date="2026-08-21"), 13846),
        (R("_11.jpg", "hoho_cutie_", "콩글리쉬로 대화하는 전소미 & 에스파 지젤", 10884, 14672,
            post_date="2026-08-22"), 10884),
        (R("_12.jpg", "laugh.34", "지젤력 실화냐..", 15361, 24878), 15361),
        (R("_13.jpg", "one_day_humor_diary", "카리나 외모는 10점 만점에?", 9458, None), 9458),
        (R("_14.jpg", "graegaja", "한 장에 8억찍고 엄마 지갑 털어간 ㄹㅈㄷ 유행 ㅋㅋ", 16000, None, rounded=True), 16000),
        (R("_15.jpg", "graegaja", "ㅘ, 이거 카리나가 다 유행시킴", 14000, None, rounded=True), 14000),
    ]),
]


def main() -> int:
    if not XLSX.exists():
        print(f"기준 파일이 없습니다: {XLSX}")
        return 1

    total = hit = 0
    problems: list[str] = []

    for vendor, target, scope, cases in CASES:
        cands = sheet.candidates_from_xlsx(XLSX, vendor, target, scope)
        readings = [c[0] for c in cases]
        expected = [c[1] for c in cases]
        matches = matcher.match_all(readings, cands, target)
        by_file = {m.reading.file: m for m in matches}

        print(f"\n{'='*94}\n{vendor}  기준일 {target}  (후보 {len(cands)}행)\n{'='*94}")
        for rd, exp in zip(readings, expected):
            m = by_file[rd.file]
            total += 1
            got_row = m.row
            if exp is None:
                ok = m.status in ("매칭실패", "검토필요") or got_row is None
                verdict = "OK(미등록 확인)" if ok else "FAIL(엉뚱한 행에 배정)"
            else:
                ok = got_row is not None and m.status in ("확정", "검토필요")
                # 기대 도달값이 그 행의 사람 입력값과 같은지도 본다
                verdict = "OK" if ok else "FAIL"
            if ok:
                hit += 1
            else:
                problems.append(f"{vendor} {rd.file}: 상태={m.status} 행={got_row.row if got_row else '-'}")

            rowdesc = f"{got_row.row}행 {got_row.업로드일} {got_row.채널명}" if got_row else "-"
            print(f"  {verdict:<18} {rd.file:<32} {rd.reach:>8,}  →  {rowdesc}")
            for w in m.warnings:
                print(f"        · {w}")

        miss = matcher.missing_rows(matches, cands)
        if miss:
            print(f"  미수신 {len(miss)}건: " + ", ".join(f"{r.채널명}({r.업로드일})" for r in miss))

    print(f"\n{'='*94}\n결과: {hit}/{total} 통과")
    if problems:
        print("문제:")
        for p in problems:
            print("  - " + p)
    return 0 if hit == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
