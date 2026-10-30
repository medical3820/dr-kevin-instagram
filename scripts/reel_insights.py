#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
발행된 릴스의 인사이트(평균 시청 시간·3초 건너뛰기 비율 등)를 모아 insights/reels.md / reels.json 으로 남긴다.

  - 대상: published.txt 에서 media_id 가 숫자인 줄 중 posts/<폴더>/post.json 이 릴스(video)인 것
  - 지표: views, reach, likes, comments, saved, shares, ig_reels_avg_watch_time(ms),
          ig_reels_video_view_total_time(ms), reels_skip_rate(%)
    (유지율 곡선·팔로우 수는 API에 없음 — 2026-10-30 문서 확인)
  - 지표 하나가 실패해도 나머지는 받는다(지표마다 따로 요청).

필요 환경변수: IG_ACCESS_TOKEN
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH = "https://graph.instagram.com/v23.0"
METRICS = ["views", "reach", "likes", "comments", "saved", "shares",
           "ig_reels_avg_watch_time", "ig_reels_video_view_total_time", "reels_skip_rate"]


def fetch(media_id, metric):
    q = urllib.parse.urlencode({"metric": metric, "access_token": TOKEN})
    try:
        with urllib.request.urlopen("%s/%s/insights?%s" % (GRAPH, media_id, q), timeout=30) as r:
            data = json.loads(r.read().decode("utf-8")).get("data", [])
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace").replace(TOKEN, "***")
        return None, "HTTP %s %s" % (e.code, msg[:160])
    except Exception as e:  # 네트워크 등
        return None, str(e)[:160]
    if not data:
        return None, "no data"
    vals = data[0].get("values") or [{}]
    return vals[0].get("value"), None


def reels():
    out = []
    for line in open(os.path.join(ROOT, "published.txt"), encoding="utf-8"):
        parts = line.split()
        if len(parts) < 2 or line.startswith("#"):
            continue
        folder, mid = parts[0], parts[1].replace("media_id=", "")
        if not mid.isdigit():
            continue
        pj = os.path.join(ROOT, "posts", folder, "post.json")
        if not os.path.exists(pj):
            continue
        post = json.load(open(pj, encoding="utf-8"))
        if not post.get("video"):
            continue
        date = parts[-1] if parts[-1][:4].isdigit() else ""
        out.append((folder, mid, date))
    return out


def main():
    if not TOKEN:
        print("IG_ACCESS_TOKEN 이 비어 있습니다.", file=sys.stderr)
        sys.exit(1)
    rows, errors = [], {}
    for folder, mid, date in reels():
        row = {"folder": folder, "media_id": mid, "published": date}
        for m in METRICS:
            v, err = fetch(mid, m)
            row[m] = v
            if err:
                errors.setdefault(m, err)
        rows.append(row)
        print(folder, {k: row[k] for k in METRICS})
    os.makedirs(os.path.join(ROOT, "insights"), exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    json.dump({"collected_at": stamp, "errors": errors, "reels": rows},
              open(os.path.join(ROOT, "insights", "reels.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def sec(ms):
        return "%.1f초" % (ms / 1000.0) if isinstance(ms, (int, float)) else "—"

    md = ["# 릴스 인사이트 (API, %s)" % stamp, "",
          "| 릴스 | 발행 | 조회 | 도달 | 평균 시청 | 3초 건너뛰기 | 좋아요 | 저장 | 공유 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        skip = r["reels_skip_rate"]
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["folder"], r["published"][:10], r["views"], r["reach"], sec(r["ig_reels_avg_watch_time"]),
            ("%s%%" % skip) if skip is not None else "—", r["likes"], r["saved"], r["shares"]))
    if errors:
        md += ["", "지표 오류(첫 번째만):"] + ["- %s: %s" % (k, v) for k, v in errors.items()]
    open(os.path.join(ROOT, "insights", "reels.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
