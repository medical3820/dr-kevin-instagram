#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube Shorts 예약 업로드 스크립트 (YouTube Data API v3, videos.insert resumable)

※ 초안 — Google API 감사(audit) 통과 전까지는 쓰지 않는다.
   감사 전 프로젝트로 올린 영상은 "비공개(잠김)"으로 고정되어 예약 공개가 되지 않는다.
   그동안은 YouTube Studio 에서 직접 예약 업로드한다. (docs/youtube_setup.md)

흐름:
  1) queue_shorts.txt 에서 아직 기록(published_shorts.txt)에 없는 폴더를 고른다
     - 예약 실행(RESPECT_PUBLISH_AT=1)은 publish_at 까지 UPLOAD_AHEAD_HOURS(기본 72) 이내인 항목만
  2) shorts/<folder>/short.json 검사 (제목·설명·태그 길이, 카테고리, 시각, 영상 파일)
  3) 중복 확인: 기록 파일의 제목 + 채널 업로드 목록(youtube.readonly 범위가 있을 때)
  4) refresh token -> access token
  5) 기록 파일에 "uploading" 줄을 먼저 남긴다  ← 어떤 이유로 끝나든 자동 재업로드를 막는다
  6) videos.insert resumable 업로드: privacyStatus=private + status.publishAt (그 시각에 공개)
  7) 기록 줄을 video_id 로 확정

인스타 중복 발행 사고(2026-10-10) 교훈:
  - 업로드가 시작된 뒤 오류가 나도 기록은 남긴다 (자동 재시도 금지, 사람이 Studio 확인 후 줄을 지운다)
  - 같은 제목은 다시 올리지 않는다

필요 환경변수:
  YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN   (GitHub Secrets)
  DRY_RUN            (선택) "1" 이면 검사까지만 — 시크릿 없이도 돈다
  RESPECT_PUBLISH_AT (선택) "1" 이면 publish_at 기준으로 업로드할 항목을 고른다 (예약 실행)
  EMPTY_OK           (선택) "1" 이면 올릴 항목이 없을 때 실패 대신 조용히 종료
  UPLOAD_AHEAD_HOURS (선택) publish_at 몇 시간 전부터 미리 올릴지. 기본 72
"""

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"

CLIENT_ID = os.environ.get("YT_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
AHEAD_HOURS = float(os.environ.get("UPLOAD_AHEAD_HOURS", "") or 72)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "queue_shorts.txt")
PUBLISHED = os.path.join(ROOT, "published_shorts.txt")
SHORTS = os.path.join(ROOT, "shorts")

KST = datetime.timezone(datetime.timedelta(hours=9))
CHUNK = 8 * 1024 * 1024          # 256KB 의 배수여야 한다
MIN_LEAD = datetime.timedelta(minutes=15)   # publishAt 은 최소 이만큼 미래여야 예약으로 올린다

_access_token = ""


def die(msg) -> NoReturn:
    print("ERROR: " + _mask(msg), file=sys.stderr)
    sys.exit(1)


def _mask(text):
    for s in (_access_token, REFRESH_TOKEN, CLIENT_SECRET):
        if s:
            text = text.replace(s, "***")
    return text


def summary(text):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


# --- 시각 --------------------------------------------------------------------

def parse_when(folder, at):
    try:
        when = datetime.datetime.fromisoformat(at)
    except ValueError:
        die("%s publish_at 형식 오류: %s (예: 2026-10-20T10:00-04:00)" % (folder, at))
    if when.tzinfo is None:
        when = when.replace(tzinfo=KST)  # 시간대 없으면 KST (publish.py 와 같은 규칙)
    return when


def fmt_times(when):
    utc = when.astimezone(datetime.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        et = utc.astimezone(ZoneInfo("America/New_York"))
    except Exception:  # 시간대 DB 가 없는 PC — 표시용이므로 EDT 로 근사
        et = utc.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))
    return "%s UTC / 미 동부 %s / 한국 %s" % (
        utc.strftime("%m-%d %H:%M"), et.strftime("%m-%d %H:%M"), utc.astimezone(KST).strftime("%m-%d %H:%M"))


# --- short.json ---------------------------------------------------------------

def load_short(folder):
    path = os.path.join(SHORTS, folder, "short.json")
    if not os.path.exists(path):
        die("short.json 을 찾을 수 없습니다: %s" % path)
    return json.load(open(path, encoding="utf-8"))


def validate(folder, s):
    """문제 목록을 돌려준다. 비어 있으면 통과."""
    p = []
    for key in ("id", "title", "description", "video", "publish_at", "category_id",
                "made_for_kids", "contains_synthetic_media"):
        if key not in s:
            p.append("%s 없음" % key)
    if p:
        return p
    title, desc = s["title"].strip(), s["description"]
    if not 1 <= len(title) <= 100:
        p.append("제목은 1~100자 (현재 %d자)" % len(title))
    if len(desc.encode("utf-8")) > 5000:
        p.append("설명은 5,000바이트 이하 (현재 %d)" % len(desc.encode("utf-8")))
    for name, text in (("제목", title), ("설명", desc)):
        if "<" in text or ">" in text:
            p.append("%s에 < 또는 > 가 있으면 YouTube 가 거부합니다" % name)
    tags = s.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        p.append("tags 는 문자열 목록이어야 합니다")
    else:
        # YouTube 규칙: 공백이 있는 태그는 따옴표 2자가 더해져 계산, 합계 500자 이하
        total = sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0)
        if total > 500:
            p.append("태그 합계 500자 초과 (%d)" % total)
    if str(s["category_id"]) not in ("26", "27"):
        p.append("category_id 는 \"27\"(Education) 또는 \"26\"(Howto & Style)")
    if s["made_for_kids"] is not False:
        p.append("made_for_kids 는 false 여야 합니다")
    if not isinstance(s["contains_synthetic_media"], bool):
        p.append("contains_synthetic_media 는 true/false 로 명시")
    video = os.path.join(SHORTS, folder, s["video"])
    if not os.path.exists(video):
        p.append("영상 파일 없음: %s" % video)
    elif os.path.getsize(video) == 0:
        p.append("영상 파일이 비어 있음")
    return p


# --- 기록 ---------------------------------------------------------------------

def read_records():
    rec = {}
    if os.path.exists(PUBLISHED):
        for line in open(PUBLISHED, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                rec[line.split()[0]] = line
    return rec


def recorded_titles(rec):
    titles = {}
    for folder in rec:
        path = os.path.join(SHORTS, folder, "short.json")
        try:
            titles[json.load(open(path, encoding="utf-8"))["title"].strip()] = folder
        except Exception:
            pass
    return titles


def write_record(folder, video_id, status, publish_at):
    """같은 폴더 줄이 있으면 교체, 없으면 추가. 업로드 시작 전과 직후 두 번 부른다."""
    line = "%s  video_id=%s  status=%s  publish_at=%s  %s" % (
        folder, video_id, status, publish_at, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    lines = open(PUBLISHED, encoding="utf-8").read().splitlines() if os.path.exists(PUBLISHED) else []
    for i, old in enumerate(lines):
        if old.split()[:1] == [folder]:
            lines[i] = line
            break
    else:
        lines.append(line)
    with open(PUBLISHED, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def drop_record(folder):
    if not os.path.exists(PUBLISHED):
        return
    lines = [l for l in open(PUBLISHED, encoding="utf-8").read().splitlines() if l.split()[:1] != [folder]]
    with open(PUBLISHED, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


# --- 대상 고르기 --------------------------------------------------------------

def pick_folder(rec):
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    respect_at = os.environ.get("RESPECT_PUBLISH_AT", "") == "1"
    now = datetime.datetime.now(datetime.timezone.utc)
    for line in open(QUEUE, encoding="utf-8"):
        folder = line.strip()
        if not folder or folder.startswith("#") or folder in rec:
            continue
        if not respect_at:
            return folder
        s = load_short(folder)
        at = (s.get("publish_at") or "").strip()
        if not at:
            print("  %s publish_at 없음 → 예약 실행 대상 아님" % folder)
            continue
        when = parse_when(folder, at)
        if when - now < MIN_LEAD:
            # 이미 지났거나 너무 임박 — 자동으로는 올리지 않는다 (공개 시각을 놓친 채 올라가는 것 방지)
            msg = "%s publish_at(%s) 이 지났거나 15분 이내 — 자동 업로드하지 않습니다. Studio 에서 직접 올리거나 publish_at 을 바꾸세요." % (folder, at)
            print("경고: " + msg)
            summary("- ⚠ " + msg)
            continue
        if when - now > datetime.timedelta(hours=AHEAD_HOURS):
            print("  %s publish_at=%s → 아직 이름 (%d시간 전부터 업로드)" % (folder, at, AHEAD_HOURS))
            continue
        return folder
    if os.environ.get("EMPTY_OK", "") == "1":
        print("queue_shorts.txt 에 지금 올릴 항목이 없어 이번 회차는 건너뜁니다.")
        sys.exit(0)
    die("업로드 대기열이 비었습니다. queue_shorts.txt 를 확인하세요.")


# --- HTTP ---------------------------------------------------------------------

class HttpError(Exception):
    def __init__(self, code, body, headers=None):
        Exception.__init__(self, "HTTP %s" % code)
        self.code = code
        self.body = body
        self.headers = headers or {}


def http(method, url, data=None, headers=None, timeout=60):
    """(status, headers, body_bytes). 2xx·308 은 정상 반환, 그 외는 HttpError."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        if e.code == 308:  # resumable 업로드의 "이어서 보내라" — 오류 아님
            return 308, e.headers, body
        raise HttpError(e.code, _mask(body.decode("utf-8", "replace")), e.headers)


def get_access_token():
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    try:
        _, _, body = http("POST", TOKEN_URL, data, {"Content-Type": "application/x-www-form-urlencoded"})
    except HttpError as e:
        hint = ""
        if "invalid_grant" in e.body:
            hint = ("\n→ refresh token 이 만료·폐기됨. OAuth 동의 화면이 '테스트' 상태면 7일마다 만료됩니다. "
                    "docs/youtube_setup.md 4단계로 다시 발급해 YT_REFRESH_TOKEN 을 교체하세요.")
        die("액세스 토큰 발급 실패 -> HTTP %s\n%s%s" % (e.code, e.body, hint))
    return json.loads(body.decode("utf-8"))["access_token"]


def api_get(path, params):
    url = "%s/%s?%s" % (API, path, urllib.parse.urlencode(params))
    _, _, body = http("GET", url, headers={"Authorization": "Bearer " + _access_token})
    return json.loads(body.decode("utf-8"))


def find_on_youtube(title):
    """채널 최근 업로드 중 제목이 같은 영상 id. 조회 불가(범위 없음 등)면 None — 업로드를 막지는 않음."""
    try:
        ch = api_get("channels", {"part": "contentDetails", "mine": "true"})
        uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        r = api_get("playlistItems", {"part": "snippet", "playlistId": uploads, "maxResults": "50"})
    except Exception as e:
        print("경고: 채널 업로드 목록 조회 실패(%s) — 기록 파일로만 중복을 확인합니다. "
              "youtube.readonly 범위를 함께 승인하면 채널까지 확인합니다." % _mask(str(e)))
        return None
    want = title.strip()
    for item in r.get("items", []):
        sn = item.get("snippet", {})
        if (sn.get("title") or "").strip() == want:
            return (sn.get("resourceId") or {}).get("videoId") or "unknown"
    return None


# --- 업로드 -------------------------------------------------------------------

def build_body(s, when):
    status = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": bool(s["contains_synthetic_media"]),
        "embeddable": True,
        "license": "youtube",
    }
    if when is not None:
        status["publishAt"] = when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "snippet": {
            "title": s["title"].strip(),
            "description": s["description"],
            "tags": s.get("tags") or [],
            "categoryId": str(s["category_id"]),
            "defaultLanguage": s.get("language", "en"),
            "defaultAudioLanguage": s.get("language", "en"),
        },
        "status": status,
    }


def start_session(body, size):
    url = "%s/videos?uploadType=resumable&part=snippet,status&notifySubscribers=true" % UPLOAD_API
    _, headers, _ = http("POST", url, json.dumps(body).encode("utf-8"), {
        "Authorization": "Bearer " + _access_token,
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(size),
    })
    loc = headers.get("Location")
    if not loc:
        die("업로드 세션 주소(Location)가 응답에 없습니다.")
    return loc


def _next_offset(headers):
    rng = headers.get("Range") if headers else None  # 예: "bytes=0-8388607"
    return int(rng.split("-")[1]) + 1 if rng else 0


def upload_bytes(session, path, size):
    """청크 업로드. 네트워크·5xx 오류는 받은 위치를 서버에 물어 이어 보낸다(최대 6회)."""
    offset, failures = 0, 0
    with open(path, "rb") as f:
        while True:
            try:
                if failures:
                    code, headers, body = http("PUT", session, b"", {
                        "Authorization": "Bearer " + _access_token,
                        "Content-Range": "bytes */%d" % size,
                    })
                    if code in (200, 201):
                        return json.loads(body.decode("utf-8"))
                    offset = _next_offset(headers)
                f.seek(offset)
                chunk = f.read(CHUNK)
                end = offset + len(chunk) - 1
                code, headers, body = http("PUT", session, chunk, {
                    "Authorization": "Bearer " + _access_token,
                    "Content-Length": str(len(chunk)),
                    "Content-Range": "bytes %d-%d/%d" % (offset, end, size),
                }, timeout=300)
                if code in (200, 201):
                    return json.loads(body.decode("utf-8"))
                offset = _next_offset(headers)
                failures = 0
                print("  %.1f%%" % (100.0 * offset / size))
            except (HttpError, urllib.error.URLError, OSError) as e:
                if isinstance(e, HttpError) and e.code < 500:
                    raise
                failures += 1
                if failures > 6:
                    raise
                wait = min(2 ** failures, 60)
                print("  업로드 중단(%s) — %d초 뒤 이어서 보냅니다 (%d/6)" % (_mask(str(e)), wait, failures))
                time.sleep(wait)


# --- main ---------------------------------------------------------------------

def main():
    global _access_token
    if not os.path.exists(QUEUE):
        die("queue_shorts.txt 가 없습니다.")
    rec = read_records()
    folder = pick_folder(rec)
    if folder in rec:
        die("%s 는 이미 기록에 있습니다:\n  %s\n다시 올리려면 Studio 에서 확인한 뒤 published_shorts.txt 의 그 줄을 지우세요."
            % (folder, rec[folder]))

    s = load_short(folder)
    problems = validate(folder, s)
    if problems:
        die("%s short.json 검사 실패:\n  - %s" % (folder, "\n  - ".join(problems)))

    title = s["title"].strip()
    same = recorded_titles(rec).get(title)
    if same:
        die("같은 제목이 이미 기록에 있습니다 (%s). 중복 업로드를 막습니다." % same)

    video = os.path.join(SHORTS, folder, s["video"])
    size = os.path.getsize(video)
    when = parse_when(folder, s["publish_at"].strip())
    now = datetime.datetime.now(datetime.timezone.utc)
    if when - now < MIN_LEAD:
        print("경고: publish_at 이 지났거나 15분 이내 → 예약 없이 '비공개'로만 올립니다. 공개는 Studio 에서 직접.")
        when = None

    print("업로드 대상: %s" % folder)
    print("  제목: %s" % title)
    print("  영상: %s (%.1fMB)" % (s["video"], size / 1024.0 / 1024.0))
    print("  공개: %s" % (fmt_times(when) if when else "예약 없음(비공개)"))
    body = build_body(s, when)

    if DRY_RUN:
        print("\n보낼 메타데이터:\n" + json.dumps(body, ensure_ascii=False, indent=2))
        print("\nDRY_RUN=1 이므로 여기서 중단합니다. short.json·영상 파일 검사는 모두 통과했습니다.")
        summary("### DRY RUN 통과: %s\n\n- 제목: %s\n- 공개: %s\n" % (
            folder, title, fmt_times(when) if when else "예약 없음"))
        return

    for name, val in (("YT_CLIENT_ID", CLIENT_ID), ("YT_CLIENT_SECRET", CLIENT_SECRET),
                      ("YT_REFRESH_TOKEN", REFRESH_TOKEN)):
        if not val:
            die("%s 가 비어 있습니다." % name)
    _access_token = get_access_token()

    dup = find_on_youtube(title)
    if dup:
        write_record(folder, dup, "skip-duplicate", s["publish_at"])
        print("같은 제목의 영상이 채널에 이미 있습니다 (video_id=%s). 올리지 않고 기록만 남깁니다." % dup)
        summary("### 건너뜀: %s\n\n같은 제목 영상이 이미 있음 (`%s`)\n" % (folder, dup))
        return

    # 업로드 전에 먼저 기록 — 이 뒤로 어떻게 끝나든(오류·시간 초과) 자동 재업로드가 일어나지 않게
    write_record(folder, "uploading", "started", s["publish_at"])
    try:
        session = start_session(body, size)
    except HttpError as e:
        drop_record(folder)  # 세션조차 못 열었으면 영상은 생기지 않았다 — 다음 회차에 다시 시도해도 안전
        hint = ""
        if e.code == 403 and "quota" in e.body.lower():
            hint = "\n→ 일일 쿼터 초과. 내일 다시 돌거나 쿼터 증설(감사 양식) 필요."
        elif e.code in (401, 403) and "scope" in e.body.lower():
            hint = "\n→ refresh token 에 youtube.upload 범위가 없습니다. 4단계를 다시."
        die("업로드 세션 생성 실패 -> HTTP %s\n%s%s" % (e.code, e.body, hint))

    try:
        video_res = upload_bytes(session, video, size)
    except BaseException as e:
        time.sleep(20)
        vid = find_on_youtube(title)
        write_record(folder, vid or "unknown", "upload-error-check-studio", s["publish_at"])
        die("업로드 오류: %r — 채널 확인 결과 %s. 자동 재업로드하지 않도록 기록했습니다. Studio 에서 확인하세요." % (
            e, "올라감 (video_id=%s)" % vid if vid else "확인 불가"))

    vid = video_res.get("id", "unknown")
    st = video_res.get("status", {})
    write_record(folder, vid, st.get("uploadStatus", "uploaded"), s["publish_at"])
    print("업로드 완료. video_id=%s  privacy=%s  publishAt=%s" % (vid, st.get("privacyStatus"), st.get("publishAt")))

    lines = ["### 업로드 완료: %s" % folder, "",
             "- video_id: `%s` — https://studio.youtube.com/video/%s/edit" % (vid, vid),
             "- 제목: %s" % title,
             "- 예약 공개: %s" % (fmt_times(when) if when else "없음 — Studio 에서 직접 공개")]
    if when and not st.get("publishAt"):
        lines.append("- **⚠ 응답에 publishAt 이 없습니다. 감사 전 프로젝트라 '비공개(잠김)'일 가능성 — "
                     "Studio 에서 확인하고, 잠겼으면 이 영상은 지우고 Studio 로 직접 다시 올리세요.**")
    summary("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
