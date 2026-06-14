# 자동화 아이디어 탐색기 MVP

커뮤니티 글에서 사람들이 반복적으로 불편해하는 일을 찾고, AI로 자동화 아이디어와 수익화 가능성을 점수화하는 MVP입니다.

## 기능

- Reddit RSS에서 자동화/반복작업/알림/정리 관련 글 수집
- OpenAI API로 문제, 대상, 자동화 아이디어, 수익화 방식 분석
- 점수 기준으로 정렬
- CSV와 HTML 리포트 생성
- 선택적으로 텔레그램 TOP 5 알림 전송

## 설치

```bash
cd automation_idea_finder
python -m venv venv
```

Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

macOS/Linux:

```bash
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 설정

`.env` 파일을 열고 OpenAI API 키를 넣으세요.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

API 키가 없어도 실행은 되지만, 키워드 기반 임시 분석만 됩니다.

## 실행

```bash
python main.py
```

실행 후 `output` 폴더에 결과가 생깁니다.

```text
output/ideas_날짜.csv
output/ideas_날짜.html
```

## 텔레그램 알림 설정 선택

1. 텔레그램에서 BotFather로 봇 생성
2. 봇 토큰 복사
3. 내 chat_id 확인
4. `.env`에 입력

```env
TELEGRAM_BOT_TOKEN=123456:xxxx
TELEGRAM_CHAT_ID=123456789
```

## 점수 의미

- 반복성: 같은 문제가 반복되는 정도
- 결제 가능성: 돈을 낼 가능성
- 개발 쉬움: 개인 개발자가 만들기 쉬운 정도
- 낮은 경쟁: 경쟁이 덜한 정도
- 자동화 적합도: 자동화로 해결하기 좋은 정도

최종 점수는 아래 가중치로 계산합니다.

```text
반복성 25%
결제 가능성 30%
개발 쉬움 15%
낮은 경쟁 15%
자동화 적합도 15%
```

## 다음 단계 아이디어

- 국내 커뮤니티 검색 추가
- GitHub Issues 수집 추가
- Product Hunt 댓글 수집 추가
- Supabase 저장
- 매일 자동 실행
- 웹 대시보드 제작
