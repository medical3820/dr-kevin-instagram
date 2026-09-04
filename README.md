# dr-kevin-instagram

Dr. Kevin Kim 인스타그램 캐러셀 발행 파이프라인.

이 저장소 하나가 **이미지 호스팅 + 콘텐츠 대기열 + 예약 발행**을 겸합니다.

> **이 저장소는 공개(public)여야 합니다.** 인스타그램 서버가 이미지를 공개 URL로 가져가야
> 발행이 되기 때문입니다. 액세스 토큰은 저장소가 아니라 GitHub Secrets에 들어가므로
> 공개 저장소여도 노출되지 않습니다.

---

## 1. 최초 설정 (한 번만)

### 1-1. 저장소를 GitHub에 올린다

GitHub Desktop → `File → Add local repository` → 이 폴더 선택 →
"create a repository" → **Public** 으로 게시.

### 1-2. Secrets 등록

저장소 페이지 → `Settings → Secrets and variables → Actions → New repository secret`

| 이름 | 값 |
|---|---|
| `IG_USER_ID` | `17841437791511654` |
| `IG_ACCESS_TOKEN` | Meta 개발자 콘솔에서 발급한 액세스 토큰 |

토큰은 이곳 외 어디에도 붙여넣지 않습니다.

### 1-3. 이미지가 실제로 열리는지 확인

`Actions → Publish carousel → Run workflow` 에서

- folder: 비워둠
- dry_run: `true`

로 한 번 돌립니다. 이미지 6장이 전부 `OK` 로 나오면 호스팅이 정상입니다.
**아직 발행되지 않습니다.**

---

## 2. 발행

`Actions → Publish carousel → Run workflow`

- **folder 비움** → `queue.txt` 맨 위의 미발행 항목
- **folder 지정** → 그 폴더를 발행 (예: `C06_glass_skin`)
- dry_run: `false`

발행이 끝나면 `published.txt` 에 기록이 자동 커밋됩니다.

### 예약 발행

`.github/workflows/publish.yml` 안의 `schedule:` 블록 주석을 풀면 자동 발행이 시작됩니다.
기본값은 화·목·토 17:00 UTC (미국 동부 오후 1시 / 한국 새벽 2시).

**테스트 발행이 성공한 뒤에 켜세요.**

---

## 3. 새 캐러셀 추가하기

1. `posts/` 아래에 폴더를 만든다 (예: `C09_sunscreen`)
2. 이미지를 `01.jpg` ~ `06.jpg` 로 넣는다
   - **JPEG, 8MB 이하, 가로 320~1440px, 비율 4:5 ~ 1.91:1, sRGB**
   - 기존 캐러셀은 1080×1350 (4:5)
3. `post.json` 을 만든다 (아래 형식)
4. `queue.txt` 맨 아래에 폴더명을 추가한다
5. push

```json
{
  "id": "C09",
  "caption": "본문 + 해시태그. 인스타 캡션 그대로 들어갑니다.",
  "first_comment": "발행 직후 자동으로 달릴 첫 댓글.",
  "slides": [
    { "file": "01.jpg", "alt_text": "Slide 1 of 6: ..." }
  ]
}
```

대체텍스트는 **125자 이하**로 씁니다. 인스타그램의 실제 상한이 100자라는 자료와
제한이 없어졌다는 자료가 엇갈려서, 어느 쪽이든 안전한 길이로 맞춘 값입니다.

---

## 4. 토큰 관리

`Actions → Token check` 가 매주 월요일 아침에 토큰 남은 기간을 확인합니다.
**남은 기간이 14일 미만이면 워크플로가 일부러 실패하고 GitHub가 알림 메일을 보냅니다.**

갱신 방법:

```bash
IG_ACCESS_TOKEN='<현재 토큰>' python3 scripts/token_status.py --print
```

출력된 새 토큰을 `IG_ACCESS_TOKEN` Secret에 덮어씁니다.

- 발급 후 24시간이 지나야 갱신이 됩니다
- 갱신에 실패해도 기존 토큰은 살아 있습니다
- 60일 넘게 방치하면 다시 발급받아야 합니다

---

## 5. 알려진 제약과 실패 지점

| 항목 | 내용 |
|---|---|
| 대체텍스트 | 캐러셀 자식 장에 `alt_text`가 실제로 반영되는지 **첫 발행 후 앱에서 직접 확인 필요**. Meta 문서 표현이 애매함 |
| 컨테이너 만료 | 생성 후 24시간 내 발행하지 않으면 만료 |
| 발행 한도 | 24시간당 100건 (캐러셀 1건 카운트) |
| 이미지 접근 | 발행 시점에 인스타 서버가 URL을 열 수 있어야 함. 저장소를 비공개로 바꾸면 즉시 깨짐 |
| 캡션 위치 | 캡션·해시태그는 **부모 컨테이너에만** 붙음. 자식에 넣으면 무시됨 |
| 첫 댓글 | 실패해도 게시물은 정상 발행됨. 로그에 경고가 남고 수동으로 달면 됨 |
| 토큰 | 60일 만료. 갱신 자동화 없이 방치하면 조용히 멈춤 |

---

## 6. 구성

```
posts/<폴더>/01.jpg ~ 06.jpg   슬라이드 이미지
posts/<폴더>/post.json         캡션 · 첫 댓글 · 대체텍스트
queue.txt                      발행 대기열 (위에서부터)
published.txt                  발행 기록 (자동)
scripts/publish.py             발행 스크립트
scripts/token_status.py        토큰 수명 확인 · 갱신
```
