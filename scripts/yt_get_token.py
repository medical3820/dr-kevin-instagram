#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube refresh token 발급 도우미 — 원장님 PC 에서 한 번만 실행 (GitHub Actions 에서는 쓰지 않음)

사용:
  python scripts/yt_get_token.py "C:\\Users\\...\\Downloads\\client_secret_xxx.json"

  1) 브라우저가 열리면 YouTube 채널 계정으로 로그인 → 권한 허용
  2) 끝나면 YT_CLIENT_ID → YT_CLIENT_SECRET → YT_REFRESH_TOKEN 을 차례로 클립보드에 복사한다.
     Enter 를 누를 때마다 다음 값으로 바뀐다. GitHub Secrets 화면에 Ctrl+V 로 붙여넣기.
  값은 화면에 출력하지 않고 파일로도 저장하지 않는다. 마지막에 클립보드를 비운다.

※ client_secret_xxx.json 은 저장소 폴더 안에 두지 말 것 (공개 저장소).
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # 중복 확인용 (채널 업로드 목록 조회)
]


def copy(text):
    subprocess.run(["clip"] if os.name == "nt" else ["pbcopy"], input=text.encode("utf-8"), check=True)


def main():
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        sys.exit("사용법: python scripts/yt_get_token.py <다운로드한 client_secret_….json 경로>")
    conf = json.load(open(sys.argv[1], encoding="utf-8"))
    conf = conf.get("installed") or conf.get("web") or {}
    client_id, client_secret = conf.get("client_id"), conf.get("client_secret")
    if not client_id or not client_secret:
        sys.exit("JSON 에 client_id/client_secret 이 없습니다. '데스크톱 앱' 유형 클라이언트의 JSON 인지 확인하세요.")

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                got.update({k: v[0] for k, v in q.items()})
            msg = "완료 — 이 창을 닫고 터미널로 돌아가세요." if "code" in q else "실패: %s" % q.get("error", ["?"])[0]
            body = ("<meta charset='utf-8'><p style='font:20px sans-serif'>%s</p>" % msg).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = "http://127.0.0.1:%d/" % srv.server_address[1]
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",          # 매번 refresh token 을 새로 받기 위해
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    print("브라우저에서 Google 로그인 창을 엽니다. 안 열리면 아래 주소를 브라우저에 붙여넣으세요:\n\n" + url + "\n")
    webbrowser.open(url)
    while not got:
        srv.handle_request()
    srv.server_close()

    if got.get("state") != state:
        sys.exit("state 값이 다릅니다. 처음부터 다시 실행하세요.")
    if "code" not in got:
        sys.exit("권한 허용이 취소되었거나 실패했습니다: %s" % got.get("error"))

    data = urllib.parse.urlencode({
        "code": got["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=60) as r:
            tok = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit("토큰 교환 실패 HTTP %s: %s" % (e.code, json.loads(e.read() or b"{}").get("error", "?")))

    refresh = tok.get("refresh_token")
    if not refresh:
        sys.exit("refresh_token 이 응답에 없습니다. myaccount.google.com → 보안 → 타사 액세스에서 이 앱 권한을 지우고 다시 실행하세요.")
    granted = tok.get("scope", "")
    print("승인된 범위: %s" % ", ".join(s.rsplit("/", 1)[-1] for s in granted.split()))
    if "youtube.upload" not in granted:
        sys.exit("youtube.upload 범위가 승인되지 않았습니다. 권한 화면에서 체크박스를 모두 켜고 다시 실행하세요.")

    for name, val in (("YT_CLIENT_ID", client_id), ("YT_CLIENT_SECRET", client_secret), ("YT_REFRESH_TOKEN", refresh)):
        copy(val)
        input("\n[%s] 클립보드에 복사됨 (%d자). GitHub 'New repository secret' 에 이름 %s 로 붙여넣고 Enter… " % (
            name, len(val), name))
    copy(" ")
    print("\n끝. 클립보드를 비웠습니다. 다운로드한 client_secret JSON 은 저장소 밖 안전한 곳에 보관하거나 지우세요.")


if __name__ == "__main__":
    main()
