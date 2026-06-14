import os
import re
import json
import csv
import time
import html
import socket
from dataclasses import dataclass, asdict
from datetime import datetime

socket.setdefaulttimeout(10)

from typing import List, Dict, Any
from urllib.parse import quote_plus

import feedparser
import pandas as pd
from dotenv import load_dotenv
from jinja2 import Template

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 처음에는 영어권 커뮤니티가 수집 안정성이 좋아 Reddit RSS부터 시작합니다.
# 필요하면 여기에 subreddit을 추가하세요.
SUBREDDITS = [
    "productivity",
    "automation",
    "NoCode",
    "smallbusiness",
    "Entrepreneur",
    "SaaS",
    "SideProject",
    "freelance",
    "learnprogramming",
]

# 사람들이 자동화를 원할 때 자주 쓰는 표현
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
]

@dataclass
class Post:
    title: str
    summary: str
    link: str
    source: str
    published: str

@dataclass
class IdeaResult:
    title: str
    source: str
    link: str
    target_user: str
    pain_point: str
    automation_idea: str
    monetization: str
    repeat_score: int
    willingness_score: int
    difficulty_score: int
    competition_score: int
    automation_fit_score: int
    final_score: float
    reason: str


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2500]


def fetch_reddit_rss(limit_per_query: int = 15) -> List[Post]:
    posts: List[Post] = []
    seen = set()

    for subreddit in SUBREDDITS:
        for query in SEARCH_QUERIES:
            url = f"https://www.reddit.com/r/{subreddit}/search.rss?q={quote_plus(query)}&restrict_sr=on&sort=new"
            feed = feedparser.parse(url, request_headers={"User-Agent": "automation-idea-finder/0.1"})
            entries = feed.entries[:limit_per_query]
            for entry in entries:
                link = getattr(entry, "link", "")
                if not link or link in seen:
                    continue
                seen.add(link)
                posts.append(Post(
                    title=clean_text(getattr(entry, "title", "")),
                    summary=clean_text(getattr(entry, "summary", "")),
                    link=link,
                    source=f"reddit/r/{subreddit}",
                    published=clean_text(getattr(entry, "published", "")),
                ))
            time.sleep(0.4)

    return posts


def heuristic_filter(posts: List[Post]) -> List[Post]:
    # 너무 넓게 가져온 글 중 자동화/불편/반복 관련 신호가 있는 글만 남김
    signals = [
        "automate", "automation", "repetitive", "manual", "annoying", "boring",
        "track", "monitor", "notify", "alert", "summarize", "organize",
        "every day", "every week", "spreadsheet", "workflow", "tool", "script",
        "i wish", "is there", "looking for", "need a way",
    ]
    filtered = []
    for post in posts:
        blob = f"{post.title} {post.summary}".lower()
        if any(s in blob for s in signals):
            filtered.append(post)
    return filtered


def analyze_with_ai(post: Post) -> IdeaResult:
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
You are an automation business idea analyst.
Analyze this community post and decide whether it reveals a useful automation opportunity.

Post title: {post.title}
Post summary: {post.summary}
Source: {post.source}

Return ONLY valid JSON with this schema:
{{
  "target_user": "who has this problem",
  "pain_point": "specific repeated pain",
  "automation_idea": "small product or automation that could solve it",
  "monetization": "specific way this could make money",
  "repeat_score": 1-10,
  "willingness_score": 1-10,
  "difficulty_score": 1-10,
  "competition_score": 1-10,
  "automation_fit_score": 1-10,
  "reason": "short Korean explanation"
}}
Scoring rules:
- repeat_score: how often the task repeats.
- willingness_score: likelihood someone would pay.
- difficulty_score: 10 means easy for a solo developer, 1 means very hard.
- competition_score: 10 means low competition, 1 means very crowded.
- automation_fit_score: how suitable it is for automation.
"""
    res = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Return only JSON. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw = res.choices[0].message.content.strip()
    data = json.loads(raw)
    final_score = round((
        data["repeat_score"] * 0.25 +
        data["willingness_score"] * 0.30 +
        data["difficulty_score"] * 0.15 +
        data["competition_score"] * 0.15 +
        data["automation_fit_score"] * 0.15
    ), 2)
    return IdeaResult(
        title=post.title,
        source=post.source,
        link=post.link,
        target_user=data.get("target_user", ""),
        pain_point=data.get("pain_point", ""),
        automation_idea=data.get("automation_idea", ""),
        monetization=data.get("monetization", ""),
        repeat_score=int(data.get("repeat_score", 1)),
        willingness_score=int(data.get("willingness_score", 1)),
        difficulty_score=int(data.get("difficulty_score", 1)),
        competition_score=int(data.get("competition_score", 1)),
        automation_fit_score=int(data.get("automation_fit_score", 1)),
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
    final_score = round((repeat_score*0.25 + willingness_score*0.30 + difficulty_score*0.15 + competition_score*0.15 + automation_fit_score*0.15), 2)

    return IdeaResult(
        title=post.title,
        source=post.source,
        link=post.link,
        target_user="반복 작업을 줄이고 싶은 사용자",
        pain_point="게시글 내용에서 반복/수동/알림/정리 관련 불편이 감지됨",
        automation_idea="키워드 감시, 요약, 알림, 정리 자동화 도구 후보",
        monetization="월 구독, 프리미엄 알림, 팀용 기능",
        repeat_score=repeat_score,
        willingness_score=willingness_score,
        difficulty_score=difficulty_score,
        competition_score=competition_score,
        automation_fit_score=automation_fit_score,
        final_score=final_score,
        reason="OPENAI_API_KEY가 없어 키워드 기반으로 임시 평가했습니다. 정확한 분석은 API 키 설정 후 가능합니다.",
    )


def analyze_posts(posts: List[Post], max_items: int = 40) -> List[IdeaResult]:
    results = []
    use_ai = bool(OPENAI_API_KEY and OPENAI_API_KEY != "your_openai_api_key_here" and OpenAI is not None)

    for idx, post in enumerate(posts[:max_items], start=1):
        print(f"[{idx}/{min(len(posts), max_items)}] analyzing: {post.title[:80]}")
        try:
            result = analyze_with_ai(post) if use_ai else analyze_heuristic(post)
            results.append(result)
        except Exception as e:
            print(f"  -> AI 분석 실패, 휴리스틱으로 대체: {e}")
            results.append(analyze_heuristic(post))
        time.sleep(0.2)

    results.sort(key=lambda x: x.final_score, reverse=True)
    return results


def save_csv(results: List[IdeaResult], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


def save_html(results: List[IdeaResult], path: str) -> None:
    template = Template("""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>자동화 아이디어 탐색 리포트</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; line-height: 1.5; background: #fafafa; }
    .card { background: white; border: 1px solid #ddd; border-radius: 12px; padding: 18px; margin-bottom: 16px; }
    .score { font-size: 22px; font-weight: bold; }
    .meta { color: #666; font-size: 13px; }
    a { color: #0b57d0; }
    table { border-collapse: collapse; margin-top: 8px; }
    td { border: 1px solid #ddd; padding: 6px 10px; }
  </style>
</head>
<body>
  <h1>자동화 아이디어 탐색 리포트</h1>
  <p class="meta">생성 시각: {{ now }}</p>
  {% for r in results %}
  <div class="card">
    <div class="score">{{ r.final_score }}/10</div>
    <h2>{{ loop.index }}. {{ r.title }}</h2>
    <p class="meta">{{ r.source }} · <a href="{{ r.link }}" target="_blank">원문 보기</a></p>
    <p><b>대상:</b> {{ r.target_user }}</p>
    <p><b>문제:</b> {{ r.pain_point }}</p>
    <p><b>자동화 아이디어:</b> {{ r.automation_idea }}</p>
    <p><b>수익화:</b> {{ r.monetization }}</p>
    <p><b>판단:</b> {{ r.reason }}</p>
    <table>
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
        f.write(template.render(results=results, now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def send_telegram_summary(results: List[IdeaResult]) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    import requests
    top = results[:5]
    lines = ["🤖 자동화 아이디어 TOP 5"]
    for i, r in enumerate(top, start=1):
        lines.append(f"\n{i}. {r.final_score}/10 - {r.automation_idea}\n문제: {r.pain_point}\n원문: {r.link}")
    text = "\n".join(lines)[:3900]
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)


def main():
    print("Reddit RSS에서 자동화 고민 글을 수집합니다...")
    posts = fetch_reddit_rss()
    print(f"수집된 글: {len(posts)}개")

    posts = heuristic_filter(posts)
    print(f"필터링 후: {len(posts)}개")

    if not posts:
        print("수집 결과가 없습니다. SEARCH_QUERIES 또는 SUBREDDITS를 조정해보세요.")
        return

    results = analyze_posts(posts, max_items=40)
    if not results:
        print("분석 결과가 없습니다.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(OUTPUT_DIR, f"ideas_{timestamp}.csv")
    html_path = os.path.join(OUTPUT_DIR, f"ideas_{timestamp}.html")

    save_csv(results, csv_path)
    save_html(results, html_path)
    send_telegram_summary(results)

    print("\n완료!")
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")
    print("\n상위 5개:")
    for r in results[:5]:
        print(f"- {r.final_score}/10 | {r.automation_idea} | {r.link}")


if __name__ == "__main__":
    main()
