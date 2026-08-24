"""바이럴 인사이트 수집 사이트.

  업체용   https://주소/?v=<토큰>       로그인 없음
  담당자용 https://주소/               비밀번호

담당자 화면에서 판독·검토·시트 반영까지 전부 됩니다. 로컬 파이썬이 필요 없습니다.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

import config
import extract
import matcher
import sheet

st.set_page_config(page_title="바이럴 인사이트 수집", page_icon="📊", layout="wide")


# ── 자격증명 (Streamlit Secrets → 환경변수) ────────────────────
def _secret(key: str):
    """secrets.toml 이 없어도 예외를 내지 않습니다 (로컬 실행)."""
    try:
        return st.secrets[key]
    except Exception:
        return None


def _boot() -> None:
    key = _secret("ANTHROPIC_API_KEY")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
    sa = _secret("google_service_account")
    if sa:
        p = Path(config.GOOGLE_CREDENTIALS)
        if not p.exists():
            p.write_text(json.dumps(dict(sa)), encoding="utf-8")


def vendors() -> dict[str, str]:
    """업체:토큰. Secrets 에 있으면 그것을 씁니다 (공개 저장소에 토큰을 안 두기 위함)."""
    v = _secret("VENDORS")
    return dict(v) if v else dict(config.VENDORS)


_boot()
if _secret("SHEET_ID"):
    config.SHEET_ID = _secret("SHEET_ID")
MAX_FILES = 60   # 한 번에 올릴 수 있는 장수 (오남용 방지)
SCOPE_LABELS = ["추적중 전체 (업크루·굿띵투유·동후작가)", "이 날짜 업로드분만 (루나앤코코)"]


def sheet_ready() -> bool:
    return Path(config.GOOGLE_CREDENTIALS).exists()


def api_ready() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@st.cache_data(ttl=120, show_spinner=False)
def candidates(vendor: str, target: date, scope: str):
    """시트에서 추적중 행을 읽습니다. 2분 캐시."""
    if sheet_ready():
        return sheet.candidates_from_sheet(vendor, target, scope)
    snap = Path(__file__).resolve().parent.parent / "실제인사이트_260823.xlsx"
    if snap.exists():
        return sheet.candidates_from_xlsx(snap, vendor, target, scope)
    return []


def run_readings(files) -> list:
    """업로드된 파일들을 판독합니다. 원본은 임시 디렉터리에만 둡니다."""
    import tempfile
    captured = datetime.now().strftime("%Y-%m-%d %H:%M")
    readings = []
    bar = st.progress(0.0, "판독 중...")
    with tempfile.TemporaryDirectory() as td:
        for i, f in enumerate(files, 1):
            p = Path(td) / f.name
            p.write_bytes(f.getbuffer())
            readings.append(extract.read_image(p, captured))
            bar.progress(i / len(files), f"판독 중... {i}/{len(files)}")
    bar.empty()
    return readings


# ══════════════════════════════════════════════════════════════
# 업체 화면
# ══════════════════════════════════════════════════════════════
def vendor_page(vendor: str) -> None:
    st.title(f"{vendor} 인사이트 업로드")

    if not api_ready():
        st.error("설정이 완료되지 않았습니다. 담당자에게 알려주세요.")
        return

    target = st.date_input("어느 날짜까지의 인사이트인가요?",
                           value=date.today() - timedelta(days=1))
    cands = candidates(vendor, target, "window")
    if not cands:
        st.error("추적 대상 게시물을 찾지 못했습니다. 담당자에게 알려주세요.")
        return

    pending = [r for r in cands if r.current_value is None]
    st.info(f"아직 안 받은 게시물 **{len(pending)}건** / 추적중 {len(cands)}건")
    with st.expander("요청 목록"):
        for r in cands:
            st.write(f"{'✅' if r.current_value is not None else '⬜'} "
                     f"**{r.채널명}** — {r.업로드일} 업로드")

    st.markdown("---")
    files = st.file_uploader("인사이트 스크린샷을 끌어다 놓으세요 (여러 장 가능)",
                             type=["png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True)
    st.caption("게시물 하나당 **도달(조회한 사람)이 보이는 화면 1장**이면 됩니다. "
               "형식은 상관없습니다 — 앱/PC, 안드로이드/아이폰, 틱톡 모두 읽습니다.")

    if files and len(files) > MAX_FILES:
        st.error(f"한 번에 {MAX_FILES}장까지 올릴 수 있습니다. 나눠서 올려주세요.")
        return
    if not files or not st.button(f"{len(files)}장 올리기", type="primary"):
        return

    matches = matcher.match_all(run_readings(files), cands, target)

    st.markdown("### 결과")
    good = 0
    for m in matches:
        r = m.reading
        head = f"**{r.channel_name or '채널명 미확인'}** · {(r.banner_text or '')[:36]}"
        if m.status in ("확정", "검토필요"):
            st.success(f"✅ {head} — 도달 **{r.reach:,}**")
            good += 1
        elif m.status == "대상아님":
            st.error(f"❌ `{r.file}` — 인사이트 화면이 아닙니다. "
                     "도달 숫자가 보이는 화면을 다시 올려주세요.")
        elif m.status == "판독실패":
            st.error(f"❌ `{r.file}` — {' '.join(m.warnings) or '숫자를 읽을 수 없습니다'}. "
                     "다시 올려주세요.")
        else:
            st.warning(f"❓ {head} — 도달 {r.reach:,} · 담당자가 확인합니다")
            good += 1

    if sheet_ready():
        sheet.append_staging(matches, target, dry_run=False)
        st.info(f"{good}건 접수되었습니다. 감사합니다!")
    else:
        st.warning("접수되었으나 시트 연결이 안 되어 있습니다. 담당자 확인이 필요합니다.")

    still = matcher.missing_rows(matches, cands)
    if still:
        st.markdown("### 아직 안 올라온 게시물")
        for r in still:
            st.write(f"⬜ **{r.채널명}** — {r.업로드일} 업로드")


# ══════════════════════════════════════════════════════════════
# 담당자 — 판독·반영
# ══════════════════════════════════════════════════════════════
def tab_run() -> None:
    c1, c2, c3 = st.columns([1, 1, 2])
    vendor = c1.selectbox("업체", list(vendors()))
    target = c2.date_input("기준일", value=date.today() - timedelta(days=1))
    scope = "day" if c3.selectbox("폴더 기준", SCOPE_LABELS).startswith("이 날짜") else "window"

    cands = candidates(vendor, target, scope)
    st.caption(f"추적중 후보 {len(cands)}행")

    files = st.file_uploader(
        "카톡으로 받은 이미지를 전부 선택해서 올리세요 (폴더 열고 Ctrl+A → 드래그)",
        type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key="admin_up")

    if files and len(files) > MAX_FILES:
        st.error(f"한 번에 {MAX_FILES}장까지 가능합니다.")
        files = None
    if files and st.button(f"{len(files)}장 판독", type="primary"):
        if not cands:
            st.error("후보 행이 없습니다. 업체명·기준일·폴더 기준을 확인하세요.")
        else:
            st.session_state["res"] = {
                "vendor": vendor, "target": target, "cands": cands,
                "matches": matcher.match_all(run_readings(files), cands, target),
                "fix": {},
            }

    res = st.session_state.get("res")
    if not res:
        return
    if res["vendor"] != vendor or res["target"] != target:
        st.info("업체 또는 기준일이 바뀌었습니다. 다시 판독해 주세요.")
        return

    matches, cands = res["matches"], res["cands"]
    counts: dict[str, int] = {}
    for m in matches:
        counts[m.status] = counts.get(m.status, 0) + 1
    st.markdown("### " + " · ".join(f"{k} {v}" for k, v in counts.items()))

    ok = [m for m in matches if m.status == "확정"]
    if ok:
        with st.expander(f"확정 {len(ok)}건 — 그대로 반영됩니다"):
            st.dataframe(
                {"파일": [m.reading.file for m in ok],
                 "채널명": [m.reading.channel_name for m in ok],
                 "배너문구": [(m.reading.banner_text or "")[:40] for m in ok],
                 "도달": [m.reading.reach for m in ok],
                 "행": [m.row.row for m in ok],
                 "업로드일": [m.row.업로드일 for m in ok],
                 "경고": [" / ".join(m.warnings) for m in ok]},
                use_container_width=True, hide_index=True)

    need = [m for m in matches if m.status in ("검토필요", "매칭실패")]
    if need:
        st.markdown(f"### 확인 필요 {len(need)}건")
        st.caption("행을 골라 주시면 반영에 포함됩니다. '건너뛰기'는 기입하지 않습니다.")
        opts = ["건너뛰기"] + [f"{r.row}행 · {r.채널명} · {r.업로드일}" for r in cands]
        for i, m in enumerate(need):
            r = m.reading
            with st.container(border=True):
                a, b = st.columns([3, 2])
                a.markdown(f"**{r.channel_name or '채널명 미확인'}** — 도달 **{r.reach:,}**"
                           + (f" / 조회 {r.views:,}" if r.views else ""))
                a.caption(f"`{r.file}` · {r.banner_text or ''}")
                for w in m.warnings:
                    a.caption(f"⚠️ {w}")
                default = 0
                if m.row is not None:
                    for j, x in enumerate(cands):
                        if x.row == m.row.row:
                            default = j + 1
                            break
                pick = b.selectbox("어느 행입니까?", opts, index=default,
                                   key=f"fix_{i}_{r.file}")
                res["fix"][r.file] = None if pick == "건너뛰기" else int(pick.split("행")[0])

    bad = [m for m in matches if m.status in ("판독실패", "대상아님")]
    if bad:
        with st.expander(f"판독 안 된 것 {len(bad)}건 — 업체에 다시 요청"):
            for m in bad:
                st.write(f"`{m.reading.file}` — {' / '.join(m.warnings)}")

    miss = matcher.missing_rows(matches, cands)
    if miss:
        with st.expander(f"미수신 {len(miss)}건"):
            for r in miss:
                st.write(f"⬜ **{r.채널명}** — {r.업로드일} 업로드 ({r.row}행)")

    st.markdown("---")
    fill = st.checkbox("측정을 건너뛴 중간 날짜 열에 직전 측정값 복사 (월요일 필수)", value=True,
                       help="월요일은 금·토·일 합산본 1개만 받으므로 금·토 열이 빕니다. "
                            "0을 넣으면 증분값이 왜곡되므로 직전 누적값을 복사합니다.")

    by_row = {r.row: r for r in cands}
    final = []
    for m in matches:
        if m.status == "확정":
            final.append(m)
        elif res["fix"].get(m.reading.file):
            final.append(matcher.Match(
                reading=m.reading, row=by_row[res["fix"][m.reading.file]],
                score=m.score, warnings=m.warnings + ["담당자가 직접 지정"], status="확정"))

    n, filled = sheet.write_values(final, target, dry_run=True, fill_gaps=fill) if final else (0, 0)
    st.write(f"반영 예정: **{n}건**" + (f" (+ 빈 날짜 열 {filled}칸)" if filled else ""))

    if not sheet_ready():
        st.warning("구글시트가 연결되지 않아 반영할 수 없습니다.")
    elif st.button(f"시트 {matcher.date_col_for(target)}열에 반영", type="primary",
                   disabled=not final):
        sheet.append_staging(final, target, dry_run=False)
        n, filled = sheet.write_values(final, target, dry_run=False, fill_gaps=fill)
        candidates.clear()
        st.success(f"{n}건 기입 완료" + (f" (빈 열 {filled}칸 채움)" if filled else ""))
        st.session_state.pop("res", None)


# ══════════════════════════════════════════════════════════════
# 담당자 — 수집 현황
# ══════════════════════════════════════════════════════════════
def tab_status() -> None:
    d = st.date_input("기준일", value=date.today() - timedelta(days=1), key="stat_d")

    names, got, marks = [], [], []
    for v in vendors():
        names.append(v)
        try:
            cs = candidates(v, d, "window")
            done = sum(1 for r in cs if r.current_value is not None)
            got.append(f"{done}/{len(cs)}")
            marks.append("✅" if cs and done == len(cs) else ("⚠️" if done else "❌"))
        except Exception as e:
            got.append("오류")
            marks.append(str(e)[:30])
    st.table({"업체": names, "수집": got, "상태": marks})

    v = st.selectbox("재요청 문구를 만들 업체", list(vendors()), key="remind_v")
    base = st.session_state.get("base_url", "")
    try:
        cs = candidates(v, d, "window")
    except Exception as e:
        st.error(f"조회 실패: {e}")
        return
    miss = [r for r in cs if r.current_value is None]
    if not miss:
        st.success("전부 수집되었습니다.")
        return
    lines = [f"안녕하세요! 아래 {len(miss)}건 인사이트만 아직 못 받았습니다. 부탁드립니다 🙏", ""]
    lines += [f"{i}. {r.채널명}  ({r.업로드일} 업로드)" for i, r in enumerate(miss, 1)]
    if base:
        lines += ["", f"업로드 링크: {base}/?v={vendors()[v]}"]
    st.text_area("복사해서 단톡방에 붙여넣기", "\n".join(lines), height=200)


# ══════════════════════════════════════════════════════════════
# 담당자 — 업체 링크
# ══════════════════════════════════════════════════════════════
def tab_links() -> None:
    base = st.text_input("이 사이트 주소", st.session_state.get("base_url", ""),
                         placeholder="https://내앱.streamlit.app")
    st.session_state["base_url"] = base.rstrip("/")
    for v, tok in vendors().items():
        st.text_input(v, f"{st.session_state['base_url']}/?v={tok}", key=f"lk_{tok}")
    st.caption("이 링크를 각 업체 단톡방에 한 번만 보내면 됩니다. "
               "토큰은 config.py 의 VENDORS 에서 바꿉니다.")


def admin_page() -> None:
    st.title("바이럴 인사이트 수집")
    c = st.columns(3)
    c[0].metric("판독 API", "연결됨" if api_ready() else "미설정")
    c[1].metric("구글시트", "연결됨" if sheet_ready() else "미설정")
    c[2].metric("모델", config.MODEL)
    if not api_ready():
        st.error("ANTHROPIC_API_KEY 가 없습니다. Secrets 에 넣어 주세요.")

    t1, t2, t3 = st.tabs(["판독·반영", "수집 현황", "업체 링크"])
    with t1:
        tab_run()
    with t2:
        tab_status()
    with t3:
        tab_links()


# ══════════════════════════════════════════════════════════════
def gate() -> bool:
    pw = _secret("ADMIN_PASSWORD")
    if not pw:
        return True   # 비밀번호 미설정 = 로컬 개발
    if st.session_state.get("auth"):
        return True
    st.title("바이럴 인사이트 수집")
    got = st.text_input("담당자 비밀번호", type="password")
    if got and got == pw:
        st.session_state["auth"] = True
        st.rerun()
    elif got:
        st.error("비밀번호가 다릅니다.")
    return False


vendors_inv = {t: v for v, t in vendors().items()}
tok = st.query_params.get("v")
if tok in vendors_inv:
    vendor_page(vendors_inv[tok])
elif tok:
    st.error("링크가 올바르지 않습니다. 담당자에게 문의해 주세요.")
elif gate():
    admin_page()
