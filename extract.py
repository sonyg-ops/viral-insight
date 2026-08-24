"""인사이트 스크린샷 1장 → 구조화된 값.

업체마다 캡처 형식이 다르다는 전제로 만들었습니다. 표준화를 요구하지 않습니다.
"""
from __future__ import annotations

import base64
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path

import anthropic
from PIL import Image

import config

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


SYSTEM = """당신은 인스타그램·틱톡 게시물 인사이트 스크린샷에서 수치를 읽는 도구입니다.

## 읽어야 하는 값: 도달 (가장 중요)
'도달'은 스크린샷에서 아래 라벨 중 하나로 나타납니다. 전부 같은 지표입니다.
  - `조회한 사람`      (안드로이드/iOS 인스타그램, 가장 흔함)
  - `도달한 계정`      (일부 iOS 인스타그램 버전)
  - `Accounts reached` (영어 UI)
  - `총 시청자 수`     (틱톡 스튜디오)

절대 혼동하지 마십시오. `조회` / `조회수` / `Views` / `게시물 조회수` 는 도달이 아닙니다.
항상 도달보다 큽니다. 두 값을 모두 읽어서 각각 reach / views 에 담으십시오.
도달 라벨이 화면에 없으면 reach 는 null 로 두고 views 만 채우십시오.
절대 views 값을 reach 에 넣지 마십시오.

## 숫자 축약 처리
`1.6만` `2.2만` `53.0K` `61.6K` 처럼 축약된 값은 그대로 환산하되
(1.6만 → 16000, 53.0K → 53000) reach_is_rounded 를 true 로 두십시오.
`16,331` 처럼 자리수가 온전하면 reach_is_rounded 는 false 입니다.

## 채널명
계정 핸들(@ 뒤 또는 프로필명)을 찾으십시오. 업체가 스크린샷 위에 큰 글씨로
채널명 라벨을 직접 얹어놓은 경우도 있습니다. 그 라벨도 채널명입니다.
대소문자·밑줄 개수·마침표를 **보이는 그대로** 옮기십시오. 추측해서 고치지 마십시오.
틱톡은 핸들 대신 표시 이름(닉네임)만 보일 수 있습니다. 그것을 쓰십시오.

## 배너문구
게시물 썸네일 이미지 안에 큰 글씨로 박혀 있는 문구입니다. 게시물 캡션이 아닙니다.
썸네일이 잘려 일부만 보이면 보이는 부분만 적고 banner_partial 을 true 로 두십시오.

## 게시일
`8월 23일 오후 10:53` 처럼 절대 날짜가 있으면 그대로 씁니다 (post_date_source="absolute").
`2일 전` `19시간 전` 같은 상대 표기만 있으면 사용자가 알려준 캡처 시각에서
역산하십시오 (post_date_source="relative").
그래프 x축 시작점으로만 추정 가능하면 post_date_source="graph".
전혀 알 수 없으면 post_date 는 null.

## 인사이트 화면이 아닌 경우
피드 화면, 그래프만 있는 화면, 프로필 화면 등 도달·조회 수치가 없는 스크린샷은
is_insight_screen 을 false 로 두고 나머지는 최대한 채우십시오.

숫자를 확실히 읽을 수 없으면 추측하지 말고 null 로 두고 notes 에 이유를 적으십시오.
잘못된 숫자는 빈칸보다 훨씬 나쁩니다."""


SCHEMA = {
    "type": "object",
    "properties": {
        "is_insight_screen": {"type": "boolean"},
        "platform": {"type": "string", "enum": ["instagram", "tiktok", "other", "unknown"]},
        "channel_name": {"type": ["string", "null"]},
        "banner_text": {"type": ["string", "null"]},
        "banner_partial": {"type": "boolean"},
        "reach": {"type": ["integer", "null"]},
        "reach_label": {"type": ["string", "null"]},
        "reach_is_rounded": {"type": "boolean"},
        "views": {"type": ["integer", "null"]},
        "views_is_rounded": {"type": "boolean"},
        "post_date": {"type": ["string", "null"]},
        "post_date_source": {
            "type": ["string", "null"],
            "enum": ["absolute", "relative", "graph", None],
        },
        "notes": {"type": "string"},
    },
    "required": [
        "is_insight_screen", "platform", "channel_name", "banner_text",
        "banner_partial", "reach", "reach_label", "reach_is_rounded",
        "views", "views_is_rounded", "post_date", "post_date_source", "notes",
    ],
    "additionalProperties": False,
}


@dataclass
class Reading:
    """이미지 1장의 판독 결과."""
    file: str
    ok: bool = False
    error: str = ""
    is_insight_screen: bool = False
    platform: str = "unknown"
    channel_name: str | None = None
    banner_text: str | None = None
    banner_partial: bool = False
    reach: int | None = None
    reach_label: str | None = None
    reach_is_rounded: bool = False
    views: int | None = None
    views_is_rounded: bool = False
    post_date: str | None = None
    post_date_source: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _encode(path: Path) -> tuple[str, str]:
    """이미지를 축소해 base64 로. 토큰 비용을 줄입니다."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        long_edge = max(im.size)
        if long_edge > config.MAX_IMAGE_EDGE:
            ratio = config.MAX_IMAGE_EDGE / long_edge
            im = im.resize((max(1, int(im.width * ratio)),
                            max(1, int(im.height * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/jpeg"


def _call(messages, use_fallbacks=True):
    """refusal 대비 서버측 fallback 을 켠 요청. 미지원 환경이면 자동으로 낮춥니다."""
    kw = dict(
        model=config.MODEL,
        max_tokens=4096,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={
            "effort": config.EFFORT,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        messages=messages,
    )
    if use_fallbacks:
        try:
            return client().beta.messages.create(
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                **kw,
            )
        except (anthropic.BadRequestError, TypeError):
            pass  # 베타 미지원 → 일반 경로로
    return client().messages.create(**kw)


def read_image(path: str | Path, captured_at: str, hint: str = "") -> Reading:
    """스크린샷 1장 판독.

    captured_at: 캡처 시각 'YYYY-MM-DD HH:MM' — '2일 전' 역산에 씁니다.
    hint: 파일명에서 얻은 힌트 등 (예: '파일명에 적힌 채널명: 8282_humor').
    """
    path = Path(path)
    r = Reading(file=path.name)
    try:
        data, media = _encode(path)
    except Exception as e:
        r.error = f"이미지 열기 실패: {e}"
        return r

    prompt = f"이 스크린샷이 캡처된 시각은 {captured_at} 입니다. 상대 시간 표기는 이 시각에서 역산하십시오."
    if hint:
        prompt += f"\n\n참고 정보: {hint}\n(참고 정보와 화면 내용이 다르면 화면 내용을 우선하되 notes 에 적으십시오.)"

    try:
        resp = _call([{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                {"type": "text", "text": prompt},
            ],
        }])
        if resp.stop_reason == "refusal":
            r.error = "모델이 응답을 거부했습니다"
            return r
        text = next(b.text for b in resp.content if b.type == "text")
        payload = json.loads(text)
    except StopIteration:
        r.error = "응답에 텍스트 블록이 없습니다"
        return r
    except Exception as e:
        r.error = f"{type(e).__name__}: {e}"
        return r

    for k, v in payload.items():
        if hasattr(r, k):
            setattr(r, k, v)
    r.ok = True
    return r


def read_folder(folder: str | Path, captured_at: str,
                filename_hints: bool = True) -> list[Reading]:
    """폴더 안 모든 이미지를 병렬 판독."""
    folder = Path(folder)
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)
    if not files:
        return []

    def job(p: Path) -> Reading:
        hint = ""
        if filename_hints:
            # 루나앤코코처럼 '0823-8282_humor.png' 형식이면 채널명을 힌트로 줍니다.
            stem = p.stem
            if "-" in stem:
                left, _, right = stem.partition("-")
                if left.isdigit() and len(left) == 4 and right:
                    hint = f"파일명에 적힌 채널명 후보: {right}"
        return read_image(p, captured_at, hint)

    with ThreadPoolExecutor(max_workers=config.CONCURRENCY) as ex:
        return list(ex.map(job, files))
