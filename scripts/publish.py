#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram 캐러셀 발행 스크립트 (Instagram API with Instagram Login)

흐름:
  1) posts/<folder>/post.json 을 읽는다
  2) 이미지 6장의 공개 URL이 실제로 열리는지 먼저 확인한다
  3) 자식 컨테이너 N개 생성 (is_carousel_item=true, alt_text 포함)
  4) 부모 캐러셀 컨테이너 생성 (media_type=CAROUSEL, caption)
  5) 컨테이너 상태가 FINISHED 될 때까지 폴링
  6) media_publish
  7) 첫 댓글 작성
  8) queue.txt -> published.txt 이동

필요 환경변수:
  IG_USER_ID        Instagram 사용자 ID (비밀 아님)
  IG_ACCESS_TOKEN   액세스 토큰 (비밀)
  RAW_BASE          이미지 공개 URL 접두사
                    예) https://raw.githubusercontent.com/<owner>/<repo>/main
  IG_API_VERSION    (선택) 기본 v23.0. 버전 오류가 나면 자동으로 무버전 재시도.
  DRY_RUN           (선택) "1" 이면 실제 발행 없이 URL 확인까지만 수행
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

GRAPH = "https://graph.instagram.com"
DEFAULT_VERSION = os.environ.get("IG_API_VERSION", "v23.0")

IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
RAW_BASE = os.environ.get("RAW_BASE", "").strip().rstrip("/")
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "queue.txt")
PUBLISHED = os.path.join(ROOT, "published.txt")


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def _request(method, path, params, use_version=True):
    """graph.instagram.com 호출. 토큰은 항상 본문/쿼리로만 보낸다."""
    base = "%s/%s" % (GRAPH, DEFAULT_VERSION) if use_version else GRAPH
    url = "%s/%s" % (base, path.lstrip("/"))
    data = dict(params)
    data["access_token"] = TOKEN
    encoded = urllib.parse.urlencode(data).encode("utf-8")

    if method == "GET":
        req = urllib.request.Request(url + "?" + encoded.decode("utf-8"), method="GET")
        body = None
    else:
        req = urllib.request.Request(url, data=encoded, method="POST")
        body = encoded

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        # 버전이 유효하지 않다는 응답이면 무버전으로 한 번 더
        if use_version and ("Unsupported" in raw or "version" in raw.lower()):
            return _request(method, path, params, use_version=False)
        # 토큰 값이 에러 메시지에 섞여 나오는 일이 없도록 마스킹
        raw = raw.replace(TOKEN, "***TOKEN***") if TOKEN else raw
        die("%s %s -> HTTP %s\n%s" % (method, path, e.code, raw))


def check_url(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ctype = resp.headers.get("Content-Type", "")
            length = int(resp.headers.get("Content-Length") or 0)
            return resp.status == 200, ctype, length
    except Exception as e:
        return False, str(e), 0


def pick_folder():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    done = set()
    if os.path.exists(PUBLISHED):
        for line in open(PUBLISHED, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                done.add(line.split()[0])
    for line in open(QUEUE, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and line not in done:
            return line
    die("발행 대기열이 비었습니다. queue.txt를 확인하세요.")


def main():
    if not IG_USER_ID:
        die("IG_USER_ID 가 비어 있습니다.")
    if not TOKEN:
        die("IG_ACCESS_TOKEN 이 비어 있습니다.")
    if not RAW_BASE:
        die("RAW_BASE 가 비어 있습니다.")

    folder = pick_folder()
    post_path = os.path.join(ROOT, "posts", folder, "post.json")
    if not os.path.exists(post_path):
        die("post.json 을 찾을 수 없습니다: %s" % post_path)

    post = json.load(open(post_path, encoding="utf-8"))
    slides = post["slides"]
    if not (2 <= len(slides) <= 10):
        die("캐러셀은 2~10장이어야 합니다. 현재 %d장." % len(slides))

    print("발행 대상: %s (%d장)" % (folder, len(slides)))

    # --- 1. 이미지 URL 사전 확인 --------------------------------------------
    urls = []
    problems = []
    for s in slides:
        url = "%s/posts/%s/%s" % (RAW_BASE, folder, s["file"])
        ok, info, length = check_url(url)
        mb = length / 1024.0 / 1024.0
        print("  %-10s %s  (%s, %.2fMB)" % (s["file"], "OK " if ok else "FAIL", info, mb))
        if not ok:
            problems.append("%s 열리지 않음: %s" % (s["file"], info))
        elif length > 8 * 1024 * 1024:
            problems.append("%s 8MB 초과 (%.2fMB)" % (s["file"], mb))
        urls.append(url)
    if problems:
        die("이미지 사전 확인 실패:\n  - " + "\n  - ".join(problems))

    if DRY_RUN:
        print("\nDRY_RUN=1 이므로 여기서 중단합니다. 이미지 URL은 모두 정상입니다.")
        return

    # --- 2. 자식 컨테이너 ----------------------------------------------------
    children = []
    for s, url in zip(slides, urls):
        params = {"image_url": url, "is_carousel_item": "true"}
        alt = (s.get("alt_text") or "").strip()
        if alt:
            params["alt_text"] = alt
        r = _request("POST", "%s/media" % IG_USER_ID, params)
        children.append(r["id"])
        print("  자식 컨테이너 %s <- %s" % (r["id"], s["file"]))

    # --- 3. 부모 캐러셀 ------------------------------------------------------
    parent = _request("POST", "%s/media" % IG_USER_ID, {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": post["caption"],
    })
    container_id = parent["id"]
    print("  캐러셀 컨테이너 %s" % container_id)

    # --- 4. 상태 폴링 --------------------------------------------------------
    for attempt in range(30):
        st = _request("GET", container_id, {"fields": "status_code,status"})
        code = st.get("status_code")
        print("  상태: %s" % code)
        if code == "FINISHED":
            break
        if code == "ERROR":
            die("컨테이너 처리 실패: %s" % st.get("status"))
        time.sleep(5)
    else:
        die("컨테이너가 FINISHED 되지 않았습니다 (2분 초과).")

    # --- 5. 발행 ------------------------------------------------------------
    pub = _request("POST", "%s/media_publish" % IG_USER_ID, {"creation_id": container_id})
    media_id = pub["id"]
    print("발행 완료. media_id=%s" % media_id)

    # --- 6. 첫 댓글 ---------------------------------------------------------
    comment = (post.get("first_comment") or "").strip()
    comment_ok = False
    if comment:
        try:
            c = _request("POST", "%s/comments" % media_id, {"message": comment})
            print("첫 댓글 완료. comment_id=%s" % c.get("id"))
            comment_ok = True
        except SystemExit:
            print("경고: 첫 댓글 실패. 게시물은 정상 발행되었습니다. 앱에서 직접 달아주세요.")

    # --- 7. 기록 ------------------------------------------------------------
    with open(PUBLISHED, "a", encoding="utf-8") as f:
        f.write("%s  media_id=%s  comment=%s  %s\n" % (
            folder, media_id, "ok" if comment_ok else "manual",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### 발행 완료: %s\n\n" % folder)
            f.write("- media_id: `%s`\n" % media_id)
            f.write("- 슬라이드: %d장\n" % len(slides))
            f.write("- 첫 댓글: %s\n" % ("자동 등록됨" if comment_ok else "실패 — 수동 등록 필요"))
            f.write("\n**대체텍스트가 실제로 반영됐는지 인스타그램 앱에서 한 번 확인하세요.** "
                    "(게시물 … → 수정 → 각 사진의 대체 텍스트)\n")


if __name__ == "__main__":
    main()
