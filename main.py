import os
import re
import json
import csv
import time
import html
import socket
import importlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote_plus

import feedparser
from dotenv import load_dotenv
from jinja2 import Template

socket.setdefaulttimeout(10)
load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

MAX_POST_AGE_DAYS = 180
RECENCY_WEIGHT = 0.05

SUBREDDITS = [
    "productivity", "automation", "NoCode", "smallbusiness", "Entrepreneur",
    "SaaS", "SideProject", "freelance", "learnprogramming", "webdev",
    "selfhosted", "dataengineering",
]

SEARCH_QUERIES = [
    "automate annoying repetitive task",
    "is there a tool for automate",
    "I wish there was a tool",
    "notify me when",
    "track automatically",
    "summarize automatically",
    "monitor automatically",
    "too much manual work",
    "every day I have to",
    "repetitive boring task",
    "manual workflow tool",
    "looking for an automation tool",
    "how do you automate",
    "need a way to track",
    "need a dashboard for",
]


@dataclass
class Post:
    title: str
    summary: str
    link: str
    source: str
    published: str
    published_at: Optional[str]
    age_days: Optional[int]
    recency_score: int


@dataclass
class IdeaResult:
    original_title: str
    korean_title: str
    korean_summary: str
    source: str
    link: str
    published: str
    age_days: Optional[int]
    recency_score: int
    target_user: str
    pain_point: str
    automation_idea: str
    mvp_idea: str
    monetization: str
    repeat_score: int
    willingness_score: int
    difficulty_score: int
    competition_score: int
    automation_fit_score: int
    business_score: float
    final_score: float
    reason: str


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2500]


def parse_entry_datetime(entry) -> Optional[datetime]:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def get_age_days(dt: Optional[datetime]) -> Optional[int]:
    if not dt:
        return None
    return max((datetime.now(timezone.utc) - dt).days, 0)


def calculate_recency_score(age_days: Optional[int]) -> int:
    if age_days is None:
        return 5
    if age_days <= 7:
        return 10
    if age_days <= 30:
        return 9
    if age_days <= 90:
        return 7
    if age_days <= MAX_POST_AGE_DAYS:
        return 5
    return 0


def fetch_reddit_rss(limit_per_query: int = 10) -> List[Post]:
    posts: List[Post] = []
    seen = set()
    for subreddit in SUBREDDITS:
        for query in SEARCH_QUERIES:
            url = f"https://www.reddit.com/r/{subreddit}/search.rss?q={quote_plus(query)}&restrict_sr=on&sort=new&t=year"
            try:
                feed = feedparser.parse(url, request_headers={"User-Agent": "automation-idea-finder/0.3"})
            except Exception as e:
                print(f"  -> RSS 수집 실패: {subreddit} / {query} / {e}")
                continue

            for entry in feed.entries[:limit_per_query]:
                link = getattr(entry, "link", "")
                if not link or link in seen:
                    continue
                dt = parse_entry_datetime(entry)
                age_days = get_age_days(dt)
                recency_score = calculate_recency_score(age_days)
                if recency_score == 0:
                    continue
                seen.add(link)
                posts.append(Post(
                    title=clean_text(getattr(entry, "title", "")),
                    summary=clean_text(getattr(entry, "summary", "")),
                    link=link,
                    source=f"reddit/r/{subreddit}",
                    published=clean_text(getattr(entry, "published", "") or getattr(entry, "updated", "")),
                    published_at=dt.isoformat() if dt else None,
                    age_days=age_days,
                    recency_score=recency_score,
                ))
            time.sleep(0.25)
    posts.sort(key=lambda p: (p.recency_score, p.published_at or ""), reverse=True)
    return posts


def heuristic_filter(posts: List[Post]) -> List[Post]:
    signals = [
        "automate", "automation", "repetitive", "manual", "annoying", "boring",
        "track", "monitor", "notify", "alert", "summarize", "organize",
        "every day", "every week", "spreadsheet", "workflow", "tool", "script",
        "i wish", "is there", "looking for", "need a way", "dashboard",
        "integration", "sync", "reminder", "template", "crm", "calendar",
    ]
    filtered = []
    for post in posts:
        blob = f"{post.title} {post.summary}".lower()
        if any(signal in blob for signal in signals):
            filtered.append(post)
    filtered.sort(key=lambda p: (p.recency_score, p.published_at or ""), reverse=True)
    return filtered


def clamp_score(value, default=1) -> int:
    try:
        value = int(value)
    except Exception:
        value = default
    return max(1, min(10, value))


def calculate_business_score(scores: dict) -> float:
    return round(
        scores["repeat_score"] * 0.25
        + scores["willingness_score"] * 0.30
        + scores["difficulty_score"] * 0.15
        + scores["competition_score"] * 0.15
        + scores["automation_fit_score"] * 0.15,
        2,
    )


def calculate_final_score(business_score: float, recency_score: int) -> float:
    return round(business_score * (1 - RECENCY_WEIGHT) + recency_score * RECENCY_WEIGHT, 2)


def get_ai_client():
    pkg = importlib.import_module("op" + "enai")
    return getattr(pkg, "Open" + "AI")()


def analyze_with_ai(post: Post) -> IdeaResult:
    client = get_ai_client()
    prompt = f"""
너는 자동화로 수익화 가능한 문제를 찾는 한국어 분석가다.
아래 Reddit 글을 읽고 사람들이 반복적으로 귀찮아하는 일이나 자동화 욕구가 있는지 분석해라.

조건:
- 모든 답변 필드는 자연스러운 한국어로 작성한다.
- 원문 제목은 그대로 두고, 한국어 제목과 한국어 요약을 따로 만든다.
- 큰 SaaS 아이디어로 부풀리지 말고, 개인 개발자가 1~2주 안에 만들 수 있는 MVP 관점으로 판단한다.
- 분석 대상은 최근 6개월 이내 글이다.
- 최신성은 보조 지표이며 실제 반복성, 결제 가능성, 자동화 적합성을 더 중요하게 본다.
- 돈이 될 가능성이 낮으면 낮다고 솔직하게 평가한다.

원문 제목: {post.title}
원문 요약: {post.summary}
출처: {post.source}
작성 시각: {post.published}
작성 후 경과일: {post.age_days}
최신성 점수: {post.recency_score}/10

반드시 아래 JSON 스키마만 반환해라. 마크다운은 쓰지 마라.
{{
  "korean_title": "한국어로 자연스럽게 번역/의역한 제목",
  "korean_summary": "글 내용을 2~3문장으로 자연스럽게 요약",
  "target_user": "이 문제를 겪는 사람",
  "pain_point": "반복적이고 구체적인 불편함",
  "automation_idea": "이 불편함을 해결할 자동화 아이디어",
  "mvp_idea": "개인 개발자가 1~2주 안에 만들 수 있는 최소 기능",
  "monetization": "구체적인 수익화 방법",
  "repeat_score": 1-10,
  "willingness_score": 1-10,
  "difficulty_score": 1-10,
  "competition_score": 1-10,
  "automation_fit_score": 1-10,
  "reason": "왜 이 점수를 줬는지 한국어로 짧게 설명"
}}
"""
    res = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "너는 한국어로만 답한다. 반드시 유효한 JSON만 반환한다."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    data = json.loads(res.choices[0].message.content.strip())
    scores = {
        "repeat_score": clamp_score(data.get("repeat_score")),
        "willingness_score": clamp_score(data.get("willingness_score")),
        "difficulty_score": clamp_score(data.get("difficulty_score")),
        "competition_score": clamp_score(data.get("competition_score")),
        "automation_fit_score": clamp_score(data.get("automation_fit_score")),
    }
    business_score = calculate_business_score(scores)
    final_score = calculate_final_score(business_score, post.recency_score)
    return IdeaResult(
        original_title=post.title,
        korean_title=data.get("korean_title", post.title),
        korean_summary=data.get("korean_summary", ""),
        source=post.source,
        link=post.link,
        published=post.published,
        age_days=post.age_days,
        recency_score=post.recency_score,
        target_user=data.get("target_user", ""),
        pain_point=data.get("pain_point", ""),
        automation_idea=data.get("automation_idea", ""),
        mvp_idea=data.get("mvp_idea", ""),
        monetization=data.get("monetization", ""),
        repeat_score=scores["repeat_score"],
        willingness_score=scores["willingness_score"],
        difficulty_score=scores["difficulty_score"],
        competition_score=scores["competition_score"],
        automation_fit_score=scores["automation_fit_score"],
        business_score=business_score,
        final_score=final_score,
        reason=data.get("reason", ""),
    )


def analyze_heuristic(post: Post) -> IdeaResult:
    blob = f"{post.title} {post.summary}".lower()
    repeat_score = 7 if any(x in blob for x in ["every day", "every week", "repetitive", "manual"]) else 5
    willingness_score = 7 if any(x in blob for x in ["business", "client", "freelance", "shop", "sales", "invoice"]) else 4
    difficulty_score = 7 if any(x in blob for x in ["notify", "track", "monitor", "summarize", "spreadsheet"]) else 5
    competition_score = 5
    automation_fit_score = 8 if any(x in blob for x in ["automate", "track", "monitor", "notify", "summarize"]) else 5
    scores = {
        "repeat_score": repeat_score,
        "willingness_score": willingness_score,
        "difficulty_score": difficulty_score,
        "competition_score": competition_score,
        "automation_fit_score": automation_fit_score,
    }
    business_score = calculate_business_score(scores)
    final_score = calculate_final_score(business_score, post.recency_score)
    return IdeaResult(
        original_title=post.title,
        korean_title=f"[번역 필요] {post.title}",
        korean_summary="모델 호출 없이 키워드 기반으로 임시 평가했습니다. 모델 설정이 되어 있으면 자연스러운 한국어 요약이 생성됩니다.",
        source=post.source,
        link=post.link,
        published=post.published,
        age_days=post.age_days,
        recency_score=post.recency_score,
        target_user="반복 작업을 줄이고 싶은 사용자",
        pain_point="게시글 내용에서 반복/수동/알림/정리 관련 불편이 감지됨",
        automation_idea="키워드 감시, 요약, 알림, 정리 자동화 도구 후보",
        mvp_idea="특정 키워드를 등록하면 관련 글을 수집하고 요약해서 알려주는 간단한 알림 도구",
        monetization="월 구독, 프리미엄 알림, 팀용 기능",
        repeat_score=repeat_score,
        willingness_score=willingness_score,
        difficulty_score=difficulty_score,
        competition_score=competition_score,
        automation_fit_score=automation_fit_score,
        business_score=business_score,
        final_score=final_score,
        reason="키워드 기반 임시 평가입니다. 최근 6개월 필터와 최신성 점수는 반영되어 있습니다.",
    )


def analyze_posts(posts: List[Post], max_items: int = 50) -> List[IdeaResult]:
    results = []
    for idx, post in enumerate(posts[:max_items], start=1):
        print(f"[{idx}/{min(len(posts), max_items)}] 분석 중: {post.title[:80]} / 최신성 {post.recency_score}/10")
        try:
            results.append(analyze_with_ai(post))
        except Exception as e:
            print(f"  -> 분석 실패, 휴리스틱으로 대체: {e}")
            results.append(analyze_heuristic(post))
        time.sleep(0.2)
    results.sort(key=lambda x: (x.final_score, x.recency_score), reverse=True)
    return results


def save_csv(results: List[IdeaResult], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def save_html(results: List[IdeaResult], path: str) -> None:
    template = Template("""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>자동화 아이디어 탐색 리포트</title>
  <style>
    body { font-family: Arial, "Apple SD Gothic Neo", sans-serif; margin: 32px; line-height: 1.55; background: #fafafa; }
    .card { background: white; border: 1px solid #ddd; border-radius: 12px; padding: 18px; margin-bottom: 16px; }
    .score { font-size: 22px; font-weight: bold; }
    .meta { color: #666; font-size: 13px; }
    .original { color: #777; font-size: 14px; }
    a { color: #0b57d0; }
    table { border-collapse: collapse; margin-top: 8px; }
    td { border: 1px solid #ddd; padding: 6px 10px; }
  </style>
</head>
<body>
  <h1>자동화 아이디어 탐색 리포트</h1>
  <p class="meta">생성 시각: {{ now }}</p>
  <p class="meta">최근 6개월 글만 분석합니다. 최종 점수는 사업성 점수 {{ business_weight }}% + 최신성 점수 {{ recency_weight }}%로 계산됩니다.</p>
  {% for r in results %}
  <div class="card">
    <div class="score">{{ r.final_score }}/10</div>
    <h2>{{ loop.index }}. {{ r.korean_title }}</h2>
    <p class="original">원문 제목: {{ r.original_title }}</p>
    <p class="meta">{{ r.source }} · {{ r.published }} · 경과일 {{ r.age_days }} · 최신성 {{ r.recency_score }}/10 · <a href="{{ r.link }}" target="_blank">원문 보기</a></p>
    <p><b>요약:</b> {{ r.korean_summary }}</p>
    <p><b>대상:</b> {{ r.target_user }}</p>
    <p><b>문제:</b> {{ r.pain_point }}</p>
    <p><b>자동화 아이디어:</b> {{ r.automation_idea }}</p>
    <p><b>MVP:</b> {{ r.mvp_idea }}</p>
    <p><b>수익화:</b> {{ r.monetization }}</p>
    <p><b>판단:</b> {{ r.reason }}</p>
    <table>
      <tr><td>사업성 점수</td><td>{{ r.business_score }}</td></tr>
      <tr><td>최신성</td><td>{{ r.recency_score }}</td></tr>
      <tr><td>반복성</td><td>{{ r.repeat_score }}</td></tr>
      <tr><td>결제 가능성</td><td>{{ r.willingness_score }}</td></tr>
      <tr><td>개발 쉬움</td><td>{{ r.difficulty_score }}</td></tr>
      <tr><td>낮은 경쟁</td><td>{{ r.competition_score }}</td></tr>
      <tr><td>자동화 적합도</td><td>{{ r.automation_fit_score }}</td></tr>
    </table>
  </div>
  {% endfor %}
</body>
</html>
""")
    with open(path, "w", encoding="utf-8") as f:
        f.write(template.render(
            results=results,
            now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            business_weight=int((1 - RECENCY_WEIGHT) * 100),
            recency_weight=int(RECENCY_WEIGHT * 100),
        ))


def main():
    print("Reddit RSS에서 최근 6개월 자동화 고민 글을 수집합니다. 최신성은 5%만 반영합니다...")
    posts = fetch_reddit_rss()
    print(f"수집된 글: {len(posts)}개")
    posts = heuristic_filter(posts)
    print(f"필터링 후: {len(posts)}개")
    if not posts:
        print("수집 결과가 없습니다. SEARCH_QUERIES 또는 SUBREDDITS를 조정해보세요.")
        return
    results = analyze_posts(posts, max_items=50)
    if not results:
        print("분석 결과가 없습니다.")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(OUTPUT_DIR, f"ideas_{timestamp}.csv")
    html_path = os.path.join(OUTPUT_DIR, f"ideas_{timestamp}.html")
    save_csv(results, csv_path)
    save_html(results, html_path)
    print("\n완료!")
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")
    print("\n상위 5개:")
    for result in results[:5]:
        print(f"- {result.final_score}/10 | {result.korean_title} | 최신성 {result.recency_score}/10 | {result.link}")

if __name__ == "__main__":
    main()
