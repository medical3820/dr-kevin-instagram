# YouTube Shorts 자동 업로드 — 원장님이 직접 하실 설정

> ## 지금 운영 방식 (중요)
> **Google API 감사(audit) 통과 전까지는 YouTube Studio에서 직접 예약 업로드합니다.**
> 감사를 받지 않은 API 프로젝트로 올린 영상은 YouTube가 **"비공개(잠김)"으로 고정**합니다.
> 예약 공개(publishAt)를 넣어도 공개되지 않고, 원장님이 공개로 바꿀 수도 없습니다.
> 그래서 감사 통과 전에는
> - `queue_shorts.txt` 는 비워 두고,
> - `Publish YouTube Short` 워크플로의 예약(schedule)은 주석 상태로 둡니다.
>   (Studio 수동 업로드와 자동 업로드가 겹치면 같은 영상이 두 번 올라갑니다.)
>
> 감사 통과 메일을 받으면 → 7단계(전환)를 따라 자동으로 바꿉니다.

비밀번호·토큰·클라이언트 보안 비밀 값은 **GitHub Secrets 화면 말고는 어디에도 붙여넣지 마세요**
(Claude 대화창, 카톡, 메모 포함). 이 저장소는 공개 저장소입니다.

준비물: YouTube 채널이 연결된 Google 계정, 이 PC(파이썬 설치됨), 브라우저.
걸리는 시간: 1~6단계 30분 정도. 감사 심사는 몇 주 걸릴 수 있습니다.

---

## 1. Google Cloud 프로젝트 만들기

1. https://console.cloud.google.com 접속 → **YouTube 채널을 소유한 Google 계정**으로 로그인
2. 위쪽 프로젝트 선택 메뉴 → **새 프로젝트**
3. 프로젝트 이름: `dr-kevin-shorts` (아무 이름이나 가능) → **만들기**
4. 만든 뒤 위쪽 메뉴에서 이 프로젝트가 선택돼 있는지 확인

## 2. YouTube Data API v3 사용 설정

1. 왼쪽 메뉴 **API 및 서비스 → 라이브러리**
2. `YouTube Data API v3` 검색 → 클릭 → **사용**

## 3. OAuth 동의 화면 (Google 인증 플랫폼)

왼쪽 메뉴 **API 및 서비스 → OAuth 동의 화면** (화면 이름이 "Google 인증 플랫폼"으로 나올 수 있음) → **시작하기**

1. **앱 정보**: 앱 이름 `Dr Kevin Shorts Uploader`, 사용자 지원 이메일 = 본인 Gmail
2. **대상(Audience)**: **외부(External)**
3. **연락처 정보**: 본인 Gmail → 동의 → **만들기**
4. **대상** 메뉴 → **테스트 사용자 → 사용자 추가** → 본인 Gmail(채널 계정) 추가 → 저장
5. **데이터 액세스** 메뉴 → **범위 추가 또는 삭제** → 아래 두 개 체크 → 업데이트 → 저장
   - `.../auth/youtube.upload` (필수 — 영상 업로드)
   - `.../auth/youtube.readonly` (권장 — 업로드 전에 채널에 같은 제목 영상이 있는지 확인해 중복을 막음)

### ⚠ "테스트" 상태의 7일 만료
게시 상태가 **테스트**이면 발급한 refresh token 이 **7일 뒤 만료**됩니다.
자동 업로드를 계속 쓰려면 **대상 → 앱 게시(Publish app) → 프로덕션으로 전환**을 눌러 두세요.
- Google 검수를 받지 않아도 본인 계정으로는 쓸 수 있습니다(사용자 100명 한도).
- 대신 4단계 로그인 때 **"Google에서 확인하지 않은 앱"** 경고가 나옵니다 →
  **고급 → Dr Kevin Shorts Uploader(으)로 이동(안전하지 않음)** 을 눌러 진행하면 됩니다. 본인이 만든 앱이라 괜찮습니다.

## 4. 데스크톱 OAuth 클라이언트 만들기

1. **클라이언트(Clients)** 메뉴 (또는 API 및 서비스 → 사용자 인증 정보) → **클라이언트 만들기 / OAuth 클라이언트 ID 만들기**
2. 애플리케이션 유형: **데스크톱 앱**, 이름: `shorts-uploader` → **만들기**
3. 만든 클라이언트 → **JSON 다운로드** → `client_secret_….json` 파일이 **다운로드 폴더**에 저장됨
   - 이 파일을 **저장소 폴더(dr-kevin-instagram) 안에 넣지 마세요.** 공개됩니다.

## 5. refresh token 발급 + GitHub Secrets 등록

토큰이 화면에 나오지 않도록 도우미 스크립트가 값을 하나씩 **클립보드에만** 복사합니다.

1. 브라우저에서 GitHub 저장소 열기:
   https://github.com/medical3820/dr-kevin-instagram → **Settings → Secrets and variables → Actions**
2. 이 PC에서 PowerShell 을 열고 (파일명은 실제 다운로드된 이름으로):

```powershell
cd "$HOME\Desktop\인스타 진행\DR_KEVIN_CAROUSELS_CLINICAL_QA_FINAL\DR_KEVIN_CAROUSELS_FINAL\dr-kevin-instagram"
python scripts\yt_get_token.py "$HOME\Downloads\client_secret_여기파일명.json"
```

3. 브라우저가 열리면 **YouTube 채널 계정**으로 로그인 → (경고가 나오면 3단계 설명대로 진행) →
   권한 체크박스 **모두 체크** → 계속 → "완료" 화면이 나오면 창 닫기
4. PowerShell 에 `[YT_CLIENT_ID] 클립보드에 복사됨` 이 뜨면:
   GitHub 에서 **New repository secret** → Name `YT_CLIENT_ID` → Secret 칸에 **Ctrl+V** → Add secret
   → PowerShell 로 돌아와 **Enter**
5. 같은 방법으로 `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` 까지 등록 (Enter 누를 때마다 다음 값이 복사됨)
6. 끝나면 스크립트가 클립보드를 비웁니다. 다운로드한 `client_secret_….json` 은 지우거나 USB 등 저장소 밖에 보관.

**확인**: Secrets 목록에 `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` 세 개가 보이면 성공
(값은 GitHub 에서도 다시 볼 수 없는 게 정상입니다).

> refresh token 은 ① 테스트 상태 7일 경과 ② myaccount.google.com → 보안 → 타사 액세스에서 앱 권한 삭제
> ③ Google 계정 비밀번호 변경 시 무효가 될 수 있습니다. 워크플로가 `invalid_grant` 로 실패하면 5단계만 다시 하면 됩니다.

## 6. 감사(Audit) 및 쿼터 증설 신청

이게 통과돼야 API 로 올린 영상이 공개·예약 공개됩니다.

- 양식: **YouTube API Services – Audit and Quota Extension Form**
  (Google 에서 이 이름으로 검색 → support.google.com/youtube/contact/yt_api_form)
- 로그인: 1단계와 같은 Google 계정
- 기본 쿼터(하루 10,000 단위)는 하루 1편 업로드에 충분하므로 **쿼터 증설은 요청하지 않고 감사(compliance audit)만** 요청합니다.

### 작성 요령 (영어로 작성 — 아래 문장을 그대로 써도 됩니다)

| 항목 | 작성 예 |
|---|---|
| 조직/개인 | 개인(의사 본인), 병원 이름·웹사이트가 있으면 함께 |
| Google Cloud 프로젝트 번호 | 콘솔 첫 화면(대시보드)의 **프로젝트 번호** (숫자) |
| API 클라이언트 이름 | Dr Kevin Shorts Uploader |
| 클라이언트 링크 | https://github.com/medical3820/dr-kevin-instagram (공개 저장소 — 코드 그대로 보여줌) |
| 사용 목적 | 아래 예문 |
| 사용하는 API | YouTube Data API v3 — `videos.insert`, `channels.list`, `playlistItems.list` |
| 사용자 수 | 1명 (본인 채널만) |
| 데이터 보관 | 업로드한 video ID 와 시각만 저장소의 텍스트 파일에 기록. 다른 사용자 데이터 수집 없음 |

사용 목적 예문:

> This is a private, internal tool used only by me (a dermatologist) to upload my own
> educational skin-care Shorts to my own YouTube channel. A GitHub Actions workflow reads a video file and
> its metadata from my repository and calls videos.insert with privacyStatus=private and status.publishAt
> so the video goes public at a scheduled time. It is not offered to any other user, it never accesses
> other channels, and it stores only the resulting video ID and timestamp. The AI-generated/altered
> content flag (containsSyntheticMedia) is set honestly for each video.

- 스크린샷/화면 녹화를 요구하면: GitHub Actions 실행 화면(dry_run 결과), OAuth 동의 화면 캡처를 첨부
- 개인정보처리방침 URL 을 요구하면: 병원 홈페이지의 개인정보처리방침 링크 (없으면 "no user data collected" 로 설명)
- 심사 중 Google 이 메일로 추가 질문을 보낼 수 있습니다 → 그 메일을 저(Claude)에게 보여 주시면 답장 초안을 써 드립니다

## 7. 감사 통과 후 전환 (그때 Claude 에게 요청)

1. `Actions → Publish YouTube Short → Run workflow` (dry_run: `true`) 로 검사만 한 번
2. 쇼츠 하나를 dry_run `false` 로 올려 Studio 에서 **"예약됨"** 으로 보이는지 확인
   (잠김/비공개 고정이면 아직 감사 반영 전 — 그 영상은 지우고 다시 Studio 수동으로)
3. 확인되면 `publish-short.yml` 의 `schedule:` 주석 해제 → 이후 `queue_shorts.txt` 에 넣은 쇼츠는
   publish_at 72시간 전부터 미리 올라가고 YouTube 가 정확한 시각에 공개합니다.
4. 그 이후로는 Studio 수동 업로드를 하지 않습니다 (중복 방지).

---

## 참고: 자동 업로드가 지키는 것

- 올리기 **직전**에 `published_shorts.txt` 에 기록 → 어떤 오류로 끝나도 같은 폴더는 다시 자동 업로드되지 않음
  (2026-10-10 인스타 중복 발행 사고 교훈). 다시 올리려면 Studio 확인 후 그 줄을 지워야 함.
- 같은 제목이 기록에 있거나 채널에 이미 있으면 올리지 않음
- 영상은 항상 `private` + 예약 공개 시각으로만 올림 (바로 공개로 올리지 않음)
- 공개 시각이 이미 지났으면 자동으로 올리지 않음
- `made_for_kids: false`, AI 생성·합성 여부(`contains_synthetic_media`)는 short.json 에 명시해야만 통과
