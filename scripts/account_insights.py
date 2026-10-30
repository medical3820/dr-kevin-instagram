#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
계정 전체 인사이트를 모아 insights/account.md / account.json 으로 남긴다. (2026-10-30 추가)

  - 게시물 전부(캐러셀·한 장·릴스): /me/media 를 끝까지 넘기며 받고, 형식별 지표를 따로 요청
      피드(캐러셀·한 장): views, reach, likes, comments, saved, shares, follows, profile_visits
      릴스: views, reach, likes, comments, saved, shares, ig_reels_avg_watch_time, reels_skip_rate
      (팔로우·프로필 방문은 피드 게시물에만 있음 — 릴스는 API에 없음)
  - 계정: 최근 14일 / 그 전 14일 합계 (도달·조회·참여 계정·프로필 링크 탭·팔로우/취소)
          일별 팔로워 증감, 팔로워 국가·나이·성별, 팔로워 접속 시간대
  - 지표 하나가 실패해도 나머지는 받는다. 실패 내용은 md 맨 아래에 남긴다.

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
FEED_METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "follows", "profile_visits"]
REEL_METRICS = ["views", "reach", "likes", "comments", "saved", "shares",
                "ig_reels_avg_watch_time", "reels_skip_rate"]
ACCOUNT_TOTALS = ["reach", "views", "accounts_engaged", "total_interactions", "profile_links_taps",
                  "follows_and_unfollows", "saves", "shares"]
errors = {}


def get(path, **params):
    params["access_token"] = TOKEN
    url = path if path.startswith("http") else "%s/%s?%s" % (GRAPH, path, urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, "HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace").replace(TOKEN, "***")[:200])
    except Exception as e:  # 네트워크 등
        return None, str(e)[:200]


def note(key, err):
    if err:
        errors.setdefault(key, err)


def all_media():
    out = []
    data, err = get("me/media", fields="id,media_type,media_product_type,timestamp,caption,permalink", limit=50)
    note("me/media", err)
    while data:
        out += data.get("data", [])
        nxt = (data.get("paging") or {}).get("next")
        if not nxt:
            break
        data, err = get(nxt)
        note("me/media(next)", err)
    return out


def media_metric(mid, metric):
    data, err = get("%s/insights" % mid, metric=metric)
    note("media:" + metric, err)
    if not data or not data.get("data"):
        return None
    return (data["data"][0].get("values") or [{}])[0].get("value")


def total(metric, since, until, breakdown=None):
    params = {"metric": metric, "period": "day", "metric_type": "total_value", "since": since, "until": until}
    if breakdown:
        params["breakdown"] = breakdown
    data, err = get("me/insights", **params)
    note("account:" + metric, err)
    if not data or not data.get("data"):
        return None
    tv = data["data"][0].get("total_value") or {}
    if breakdown and tv.get("breakdowns"):
        return {"total": tv.get("value"),
                "by": {"/".join(r.get("dimension_values", [])): r.get("value")
                       for r in tv["breakdowns"][0].get("results", [])}}
    return tv.get("value")


def demographics(metric, breakdown):
    data, err = get("me/insights", metric=metric, period="lifetime", metric_type="total_value",
                    timeframe="this_month", breakdown=breakdown)
    note("%s:%s" % (metric, breakdown), err)
    if not data or not data.get("data"):
        return None
    tv = data["data"][0].get("total_value") or {}
    res = (tv.get("breakdowns") or [{}])[0].get("results", [])
    return sorted([("/".join(r.get("dimension_values", [])), r.get("value", 0)) for r in res],
                  key=lambda x: -x[1])


def folder_of(caption, posts):
    first = (caption or "").strip().split("\n")[0][:60]
    for folder, cap in posts:
        if first and cap.startswith(first):
            return folder
    return ""


def local_posts():
    out = []
    for folder in sorted(os.listdir(os.path.join(ROOT, "posts"))):
        pj = os.path.join(ROOT, "posts", folder, "post.json")
        if os.path.exists(pj):
            out.append((folder, (json.load(open(pj, encoding="utf-8")).get("caption") or "").strip()))
    return out


def main():
    if not TOKEN:
        print("IG_ACCESS_TOKEN 이 비어 있습니다.", file=sys.stderr)
        sys.exit(1)
    profile, err = get("me", fields="username,followers_count,follows_count,media_count")
    note("me", err)
    posts = local_posts()
    rows = []
    for m in all_media():
        reel = m.get("media_product_type") == "REELS"
        row = {"id": m["id"], "date": m.get("timestamp", "")[:10],
               "kind": "R" if reel else ("C" if m.get("media_type") == "CAROUSEL_ALBUM" else "S"),
               "folder": folder_of(m.get("caption"), posts),
               "first_line": (m.get("caption") or "").strip().split("\n")[0][:70],
               "permalink": m.get("permalink")}
        for metric in (REEL_METRICS if reel else FEED_METRICS):
            row[metric] = media_metric(m["id"], metric)
        rows.append(row)
        print(row["date"], row["kind"], row["folder"] or row["first_line"][:30], row.get("reach"))

    now = int(time.time())
    day = 86400
    windows = {"최근 14일": (now - 14 * day, now), "그 전 14일": (now - 28 * day, now - 14 * day)}
    account = {}
    for name, (s, u) in windows.items():
        account[name] = {}
        for metric in ACCOUNT_TOTALS:
            bd = "follow_type" if metric == "follows_and_unfollows" else None
            account[name][metric] = total(metric, s, u, bd)

    fc, err = get("me/insights", metric="follower_count", period="day", since=now - 29 * day, until=now)
    note("account:follower_count", err)
    daily = [(v.get("end_time", "")[:10], v.get("value")) for v in ((fc or {}).get("data") or [{}])[0].get("values", [])] if fc else []

    demo = {b: demographics("follower_demographics", b) for b in ("country", "age", "gender")}
    engaged = {b: demographics("engaged_audience_demographics", b) for b in ("country", "age")}
    online, err = get("me/insights", metric="online_followers", period="lifetime")
    note("account:online_followers", err)
    online_vals = (((online or {}).get("data") or [{}])[0].get("values") or [{}])[0].get("value") if online else None

    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    os.makedirs(os.path.join(ROOT, "insights"), exist_ok=True)
    json.dump({"collected_at": stamp, "profile": profile, "account": account, "follower_daily": daily,
               "follower_demographics": demo, "engaged_demographics": engaged, "online_followers": online_vals,
               "media": rows, "errors": errors},
              open(os.path.join(ROOT, "insights", "account.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    def v(x):
        return "—" if x is None else str(x)

    p = profile or {}
    md = ["# 계정 인사이트 (API, %s)" % stamp, "",
          "팔로워 %s · 팔로잉 %s · 게시물 %s" % (v(p.get("followers_count")), v(p.get("follows_count")),
                                          v(p.get("media_count"))), "",
          "## 계정 합계", "", "| 지표 | " + " | ".join(windows) + " |", "|---|" + "---|" * len(windows)]
    for metric in ACCOUNT_TOTALS:
        md.append("| %s | %s |" % (metric, " | ".join(
            json.dumps(account[w][metric], ensure_ascii=False) if isinstance(account[w][metric], dict)
            else v(account[w][metric]) for w in windows)))
    if daily:
        md += ["", "## 일별 팔로워 증감(최근 30일)", "", " ".join("%s:%s" % (d[5:], c) for d, c in daily)]
    md += ["", "## 팔로워 구성 (상위)"]
    for b, lst in demo.items():
        if lst:
            tot = sum(c for _, c in lst) or 1
            md.append("- %s: %s" % (b, ", ".join("%s %d%%" % (k, round(100.0 * c / tot)) for k, c in lst[:8])))
    for b, lst in engaged.items():
        if lst:
            tot = sum(c for _, c in lst) or 1
            md.append("- 참여한 사람 %s: %s" % (b, ", ".join("%s %d%%" % (k, round(100.0 * c / tot)) for k, c in lst[:8])))
    if isinstance(online_vals, dict) and online_vals:
        md.append("- 팔로워 접속(UTC 시각:수): " + " ".join("%s:%s" % (h, online_vals[h])
                                                    for h in sorted(online_vals, key=lambda h: int(h))))

    md += ["", "## 게시물별 (최신순)", "",
           "| 날짜 | 형식 | 게시물 | 조회 | 도달 | 저장 | 공유 | 좋아요 | 팔로우 | 프로필 방문 | 3초 건너뛰기 |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["date"], r["kind"], r["folder"] or r["first_line"].replace("|", "/")[:40], v(r.get("views")),
            v(r.get("reach")), v(r.get("saved")), v(r.get("shares")), v(r.get("likes")),
            v(r.get("follows")), v(r.get("profile_visits")),
            ("%s%%" % r["reels_skip_rate"]) if r.get("reels_skip_rate") is not None else "—"))
    if errors:
        md += ["", "지표 오류(종류별 첫 번째):"] + ["- %s: %s" % (k, e) for k, e in errors.items()]
    open(os.path.join(ROOT, "insights", "account.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
