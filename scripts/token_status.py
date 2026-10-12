#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
토큰 수명 확인 + 갱신.

  python3 scripts/token_status.py           # 남은 기간만 확인 (갱신 시도 포함)
  python3 scripts/token_status.py --print   # 갱신된 토큰을 stdout으로 출력 (로컬 전용)

Instagram Login 방식의 장기 토큰은 다음 엔드포인트로 갱신합니다.
  GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token

주의:
  - 발급 후 24시간이 지나야 갱신이 가능합니다.
  - 만료 60일 이내여야 갱신됩니다.
  - 갱신에 실패해도 기존 토큰은 그대로 살아 있습니다.
  - --print 없이는 토큰 값을 절대 출력하지 않습니다. (CI 로그 노출 방지)
"""

import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
WANT_PRINT = "--print" in sys.argv

if not TOKEN:
    print("ERROR: IG_ACCESS_TOKEN 이 비어 있습니다.", file=sys.stderr)
    sys.exit(1)

url = "https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode({
    "grant_type": "ig_refresh_token",
    "access_token": TOKEN,
})

try:
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    raw = e.read().decode("utf-8", "replace").replace(TOKEN, "***TOKEN***")
    print("갱신 호출 실패 (HTTP %s)\n%s" % (e.code, raw), file=sys.stderr)
    print("\n참고: 발급 후 24시간이 안 지났거나, 이 토큰이 갱신 대상이 아닐 수 있습니다.",
          file=sys.stderr)
    sys.exit(2)

expires_in = int(data.get("expires_in", 0))
days = expires_in / 86400.0
print("토큰 남은 기간: %.1f일 (%d초)" % (days, expires_in))

new_token = (data.get("access_token") or "").strip()
rotated = bool(new_token) and new_token != TOKEN
print("갱신 결과: %s" % ("새 토큰 발급 → Secret 교체 필요" if rotated else "기존 토큰 그대로 연장"))

summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as f:
        f.write("### 토큰 상태\n\n- 남은 기간: **%.1f일**\n" % days)
        f.write("- 갱신 결과: **%s**\n" % ("Secret 교체 필요" if rotated else "자동 연장"))

if WANT_PRINT:
    print(data.get("access_token", ""))

# 14일 미만이면 실패로 끝내 GitHub가 알림 메일을 보내게 한다
if days < 14:
    print("\n경고: 남은 기간이 14일 미만입니다. 토큰을 갱신해 GitHub Secret을 교체하세요.",
          file=sys.stderr)
    sys.exit(3)

# 갱신이 기존과 다른 토큰을 돌려줬다면, 저장된 Secret 의 만료일은 연장되지 않는다.
# NEW_TOKEN_FILE 이 주어지면(워크플로에 GH_PAT_SECRETS 가 등록된 경우) 새 토큰을 파일로 넘기고
# 다음 단계가 Secret 을 교체한다. 토큰 값은 로그에 절대 찍지 않는다.
new_token_file = os.environ.get("NEW_TOKEN_FILE", "").strip()
if rotated and new_token_file:
    with open(new_token_file, "w", encoding="utf-8") as f:
        f.write(new_token)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("rotated=1\n")
    print("새 토큰을 다음 단계(Secret 자동 교체)로 넘깁니다.")
    sys.exit(0)

# 자동 교체 설정이 없으면 실패로 끝내 알림을 보낸다.
if rotated:
    print("\n경고: 갱신 결과가 기존 토큰과 다릅니다. 저장된 IG_ACCESS_TOKEN 의 만료일은 "
          "연장되지 않았습니다. 로컬에서 token_status.py --print 로 새 토큰을 받아 "
          "Secret 을 교체하세요.", file=sys.stderr)
    sys.exit(4)
