"""설정값. 여기만 고치면 됩니다."""

# ── 판독 모델 ────────────────────────────────────────────────
# claude-opus-5  : 가장 정확. 이미지 1장 약 8원.
# claude-sonnet-5: 약 1/2 비용.
# claude-haiku-4-5: 약 1/5 비용. 대량 처리용.
MODEL = "claude-opus-5"

# 판독 신중함. low / medium / high
EFFORT = "medium"

# 이미지 긴 변 최대 픽셀. 클수록 정확하지만 비쌈. 1568이 API 권장 상한.
MAX_IMAGE_EDGE = 1568

# 동시 판독 개수
CONCURRENCY = 6


# ── 구글시트 ─────────────────────────────────────────────────
SHEET_ID = "10WpAQU9TAsi3hRZ3ELvcQYj7Z228ILXfF6BUGz495Ak"
TAB_RD = "콘텐츠 대시보드 연동"
TAB_STAGING = "_배너인사이트_자동수집"

# 서비스 계정 키 파일 경로 (없으면 --sheet 옵션을 못 씁니다)
GOOGLE_CREDENTIALS = "service_account.json"

# RD 시트 열 번호 (1부터). 헤더 기준.
COL = {
    "업로드일": 1,
    "게시물URL": 2,
    "채널명": 3,
    "채널분류": 4,
    "소재명": 5,
    "상품명": 6,
    "비용": 7,
    "누적조회수": 8,
    "증분값": 9,
    "CPV": 10,
    "기획자": 11,
    "제작자": 12,
    "캡션": 13,
    "업체명": 14,
    "상태": 15,
}
FIRST_DATE_COL = 16          # P열
FIRST_DATE = "2026-05-17"    # P열이 가리키는 날짜
HEADER_ROW = 1

# 이 분류만 대상으로 삼습니다
CHANNEL_FILTER = "바이럴 (배너)"

# 업로드일이 기준일로부터 며칠 이내인 행만 후보로 봅니다
TRACKING_WINDOW_DAYS = 12


# ── 매칭 기준 ────────────────────────────────────────────────
# 채널명이 일치해야 후보로 인정. 배너문구는 보조 점수.
SCORE_CHANNEL_EXACT = 100
SCORE_CHANNEL_NEAR = 70      # 채널명이 거의 같을 때 (laugh.34 vs laugh.35)
CHANNEL_NEAR_RATIO = 0.80    # 이 이상 닮으면 근사일치로 봅니다
SCORE_DATE_MATCH = 30
SCORE_BANNER_MAX = 40

# 1위와 2위 점수 차이가 이보다 작으면 '애매함'으로 표시
AMBIGUOUS_MARGIN = 15
# 총점이 이보다 낮으면 '매칭실패'
MIN_SCORE = 60


# ── 업체 목록 (Streamlit 업로드 페이지용) ──────────────────────
# 업체명: URL 토큰.  토큰은 아무 문자열이나 되지만 추측 어렵게.
VENDORS = {
    "업크루": "upcrew-7k2m",
    "굿띵투유": "goodthing-a3f9",
    "루나앤코코": "lunacoco-q8w4",
    "동후작가": "donghu-z5x1",
}
