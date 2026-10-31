#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
受験ニュース自動要約スクリプト (generate_news.py)
Google News RSS から「中学受験」「高校受験」「大学受験」の最新記事を取得し、
Gemini AI で 3行要約（30秒で読める形式）を生成して docs/index.html および docs/archive.json に出力します。
"""

import os
import sys
import json
import re
import html
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import time
from datetime import datetime, timezone, timedelta

# 日本時間 (JST)
JST = timezone(timedelta(hours=9))

# 1カテゴリあたりの表示件数
MAX_ITEMS_PER_CATEGORY = 6
# 許容する最大経過日数（古い記事を遮断）
MAX_ARTICLE_AGE_DAYS = 28

CATEGORIES = [
    {
        "id": "junior",
        "name": "中学受験",
        "query": (
            '(千葉 OR 渋幕 OR 市川 OR 東邦大東邦 OR 昭和秀英 OR 専修大松戸 '
            'OR 芝浦工大柏 OR 麗澤 OR 四谷大塚 OR 首都圏 OR 開成 OR 桜蔭 OR 日能研 OR SAPIX) '
            '(中学受験 OR 中学入試)'
        ),
        "icon": "🏫",
        "desc": "千葉県内（渋幕・市川・東邦・秀英・専松等）・四谷大塚・首都圏の中学入試最新トレンド"
    },
    {
        "id": "high",
        "name": "高校受験",
        "query": (
            '(高校受験 OR 高校入試 OR 公立高校入試 OR 私立高校入試 OR 都立高校 OR 千葉県立高 OR 内申点 OR 高校無償化) '
            '(千葉 OR 東京 OR 都立 OR 神奈川 OR 埼玉 OR 首都圏 OR 調査書 OR 模試 OR 進路) '
            '-中学受験 -中学入試 -大学受験 -大学入試 when:30d'
        ),
        "icon": "🎒",
        "desc": "千葉県公立・私立高校入試（日程・倍率・選抜制度）および首都圏の最新動向"
    },
    {
        "id": "univ",
        "name": "大学受験",
        "query": (
            '(首都圏 OR 東京 OR 千葉大 OR 筑波大 OR 共通テスト OR 大学入試センター '
            'OR 国公立大 OR 早慶 OR MARCH OR GMARCH OR 総合型選抜 OR 新課程) '
            '(大学受験 OR 大学入試)'
        ),
        "icon": "🎓",
        "desc": "千葉大・首都圏難関大・GMARCHを中心に共通テスト・総合型選抜・新課程入試の重要動向"
    }
]

# 首都圏外の地方ニュース除外キーワード（タイトル・配信元に含まれる場合）
EXCLUDED_PREF_KEYWORDS = [
    "宮崎", "栃木", "広島", "山口", "愛媛", "宮城", "静岡", "北海道", "沖縄",
    "福岡", "大阪", "岡山", "京都", "兵庫", "富山", "石川", "愛知", "長野",
    "新潟", "福島", "熊本", "鹿児島", "岩手", "青森", "秋田", "山形", "三重",
    "滋賀", "奈良", "和歌山", "鳥取", "島根", "香川", "徳島", "高知", "佐賀",
    "長崎", "大分", "山梨", "岐阜", "日本海", "四国", "中国新聞", "神戸新聞",
    "西日本新聞", "南日本新聞", "河北新報"
]

# 受験・教育と無関係な一般ニュース（事件・事故・スポーツ・天気・イベント・個人ブログ等）の除外パターン
NON_EXAM_NOISE_REGEX = re.compile(
    r"(刺され|刺傷|刺す|包丁|逮捕|容疑|傷害|事件|事故|不正アクセス|サイバー攻撃|流出|不祥事|体罰|"
    r"雨雲レーダー|過去の天気|実況天気|マリーンズ|ジェッツ|アルティーリ|ハピネッツ|"
    r"Ｊ１|Ｊ２|J1|J2|B\.LEAGUE|プロ野球|ドラフト名鑑|試合結果|試合情報|"
    r"無料イベント\d+選|障がい者雇用|Basket|バスケ|サッカー|野球|春高バレー|バレー|高校野球|"
    r"陸上|駅伝|マラソン|新人戦|高校総体|インターハイ|部活動の特別強化|部活動特別強化|いのちの現場|日記|ニート)"
)

# 受験・進学・教育ニュースであることを保証するキーワードパターン
EXAM_RELEVANCE_REGEX = re.compile(
    r"(受験|入試|中学|高校|高専|大学|学園|学院|付属|附属|模試|偏差値|倍率|出願|志願|"
    r"合格|進学|塾|四谷大塚|合不合|組分け|SAPIX|サピックス|日能研|早稲アカ|Vもぎ|Sもぎ|"
    r"進研|共通テスト|選抜|推薦|内申|調査書|英検|漢検|数検|検定|無償化|新課程|過去問|"
    r"併願|公立|私立|国立|都立|県立|教育|学習|勉強|学参|参考書|説明会|相談|10：0|10:0|定員|募集人員)"
)


def load_api_key():
    """環境変数または .env ファイルから API キーを取得"""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    env_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
    ]
    for p in env_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                pass
    return ""


def make_article_id(clean_title):
    """記事タイトルから一意の短いハッシュIDを生成（既読・ブックマーク・キャッシュ管理用）"""
    norm = re.sub(r"[\s\W]", "", clean_title)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]


def make_dedup_key(clean_title):
    """先頭共通プレフィックスを除去した重複判定キーを生成"""
    stripped = re.sub(r"^(\[[^\]]+\]|【[^】]+】|［[^］]+］|＜[^＞]+＞|<[^>]+>)\s*", "", clean_title)
    norm = re.sub(r"[\s\W]", "", stripped)
    return norm[:22] if norm else re.sub(r"[\s\W]", "", clean_title)[:22]


def is_similar_title(title_a, title_b, threshold=0.55):
    """2つのタイトルの文字2-gram Jaccard類似度を計算し、同一ニュースの別配信元重複を判定"""
    def bigrams(s):
        s = re.sub(r"^(\[[^\]]+\]|【[^】]+】|［[^］]+］)\s*", "", s)
        s = re.sub(r"[\s\W]", "", s)
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    bg_a = bigrams(title_a)
    bg_b = bigrams(title_b)
    if not bg_a or not bg_b:
        return False
    intersection = len(bg_a & bg_b)
    union = len(bg_a | bg_b)
    return (intersection / union) >= threshold


def clean_rss_description(raw_desc, main_title):
    """RSSの <description> からHTMLタグを除去し、関連見出し・抜粋テキストを抽出"""
    if not raw_desc:
        return ""
    text = html.unescape(raw_desc)
    text = re.sub(r"</?(li|p|br|div)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or len(line) < 8:
            continue
        if line == main_title or main_title in line:
            continue
        lines.append(line)
    return " / ".join(lines[:3])[:260]


def detect_topic_badge(category_id, title):
    """記事タイトルから指導現場・保護者向けの注目カテゴリバッジを自動判定"""
    if re.search(r"(千葉|渋幕|市川|東邦|秀英|専修大松戸|専松|芝浦工大柏|麗澤|八千代|流経|成田|国府台|船橋|東葛|佐倉|薬園台|小金|幕張|日大習志野|Vもぎ|Sもぎ|進研)", title):
        return {"label": "📍千葉注目", "cls": "badge-chiba"}
    if re.search(r"(四谷大塚|合不合|組分け|模試|偏差値|倍率|志願者|合格実績|SAPIX|日能研|早稲アカ|駿台|10：0|10:0)", title):
        return {"label": "📊模試・倍率", "cls": "badge-exam"}
    if re.search(r"(英検|英語|漢検|数検|検定|スコア|帰国)", title):
        return {"label": "🏅英語・検定", "cls": "badge-cert"}
    if re.search(r"(出願|日程|募集|要項|無償化|制度|新課程|共通テスト|総合型|推薦|調査書|内申|選抜|発表|定員|人員)", title):
        return {"label": "📝制度・日程", "cls": "badge-system"}
    return {"label": "💡学習・戦略", "cls": "badge-strategy"}


def parse_pub_date(pub_date_str, now_jst):
    """RFC 2822 pubDate をパースし、(dt_jst, 表示用日時文字列, is_new) を返す"""
    try:
        dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
        dt_jst = dt.replace(tzinfo=timezone.utc).astimezone(JST)
        diff = now_jst - dt_jst
        is_new = diff.total_seconds() <= 36 * 3600  # 36時間以内をNEW扱い
        if dt_jst.date() == now_jst.date():
            disp = f"本日 {dt_jst.strftime('%H:%M')}"
        elif dt_jst.date() == (now_jst - timedelta(days=1)).date():
            disp = f"昨日 {dt_jst.strftime('%H:%M')}"
        else:
            disp = dt_jst.strftime("%m/%d %H:%M")
        return dt_jst, disp, is_new
    except Exception:
        return now_jst, "本日更新", True


def fetch_rss_xml(query, retries=3):
    """指数バックオフ付きで Google News RSS XML を取得"""
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except Exception as e:
            print(f"  [警告] RSS取得リトライ ({attempt + 1}/{retries}): {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def fetch_rss_news(category, now_jst, global_seen_keys, global_seen_titles, max_items=MAX_ITEMS_PER_CATEGORY):
    """Google News RSS から指定カテゴリの最新ニュースを取得・ノイズ除去・最新順ソート"""
    cat_id = category["id"]
    xml_data = fetch_rss_xml(category["query"])
    if not xml_data:
        return []

    try:
        root = ET.fromstring(xml_data)
    except Exception as e:
        print(f"RSS XMLパースエラー ({cat_id}): {e}", file=sys.stderr)
        return []

    candidates = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date_str = item.findtext("pubDate", "").strip()
        raw_desc = item.findtext("description", "").strip()
        source_elem = item.find("source")
        source = source_elem.text.strip() if source_elem is not None and source_elem.text else "ニュース速報"

        # 写真・画像のみの重複記事を除外
        if re.search(r"(\d+枚目の写真|写真・画像|フォト)", title):
            continue

        # タイトル末尾の「 - メディア名」および「＜PR＞」表記を整理
        clean_title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
        clean_title = re.sub(r"\s*(＜PR＞|<PR>|\[PR\]|［PR］|【PR】)\s*$", "", clean_title, flags=re.IGNORECASE).strip()

        if not clean_title:
            continue

        # 1. 広告企画記事や一般ニュース（事件・事故・天気・スポーツ等）を除外
        if re.match(r"^(\[PR\]|［PR］|【PR】|<PR>|＜PR＞|PR[:：])", clean_title, flags=re.IGNORECASE):
            continue
        if NON_EXAM_NOISE_REGEX.search(clean_title):
            continue

        # 2. 受験・教育関連キーワードが含まれているか検証
        if not EXAM_RELEVANCE_REGEX.search(clean_title):
            continue

        # 3. カテゴリ誤混入の防止
        if cat_id == "high" and re.search(r"(【中学受験|中学受験|中学入試|私立中学|小6|男子中学)", clean_title):
            continue
        if cat_id == "univ" and re.search(r"(【中学受験|【高校受験|中学受験|中学入試|高校受験|高校入試)", clean_title):
            continue

        # 4. 首都圏外の地方ニュースの除外（千葉・東京・都立・首都圏・関東・神奈川・埼玉・茨城を含まない場合）
        has_kanto_target = re.search(
            r"(千葉|東京|都立|首都圏|関東|神奈川|埼玉|茨城|渋幕|市川|東邦|秀英|専松|専修大松戸|芝浦工大柏|麗澤|八千代|四谷大塚|早慶|MARCH|共通テスト|高校無償化|駿台)",
            clean_title
        )
        if not has_kanto_target and (
            any(pref in clean_title for pref in EXCLUDED_PREF_KEYWORDS) or
            any(pref in source for pref in EXCLUDED_PREF_KEYWORDS)
        ):
            continue

        # 5. 日付パースと古い記事の遮断
        dt_jst, pub_disp, is_new = parse_pub_date(pub_date_str, now_jst)
        age_days = (now_jst - dt_jst).total_seconds() / 86400.0
        if age_days > MAX_ARTICLE_AGE_DAYS:
            continue

        # 6. 重複排除（キー一致＋2-gram類似度判定）
        dedup_key = make_dedup_key(clean_title)
        if dedup_key in global_seen_keys:
            continue
        if any(is_similar_title(clean_title, prev_t) for prev_t in global_seen_titles):
            continue

        global_seen_keys.add(dedup_key)
        global_seen_titles.append(clean_title)

        desc_snippet = clean_rss_description(raw_desc, clean_title)
        badge = detect_topic_badge(cat_id, clean_title)
        article_id = make_article_id(clean_title)

        candidates.append({
            "id": article_id,
            "category_id": cat_id,
            "title": clean_title,
            "raw_title": title,
            "description": desc_snippet,
            "link": link,
            "pub_date": pub_disp,
            "pub_iso": dt_jst.isoformat(),
            "pub_ts": int(dt_jst.timestamp()),
            "is_new": is_new,
            "source": source,
            "badge_label": badge["label"],
            "badge_cls": badge["cls"],
            "headline": "",
            "points": [],
            "takeaway": "",
            "is_ai_summary": False
        })

    # 最新順（降順）にソートして上位 max_items 件を返す
    candidates.sort(key=lambda x: x["pub_ts"], reverse=True)
    return candidates[:max_items]


def load_archive(archive_path):
    """過去記事アーカイブ（JSONキャッシュ）を読み込む"""
    if not os.path.exists(archive_path):
        return {}
    try:
        with open(archive_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("articles", {}) if isinstance(data, dict) else {}
    except Exception as e:
        print(f"  [警告] アーカイブ読み込み失敗: {e}", file=sys.stderr)
        return {}


def save_archive(archive_path, archive_dict, now_jst):
    """要約済み記事をアーカイブ（最大120件、新しい順）として保存"""
    try:
        sorted_items = sorted(
            archive_dict.values(),
            key=lambda x: x.get("pub_ts", 0),
            reverse=True
        )[:120]
        out_dict = {item["id"]: item for item in sorted_items if "id" in item}
        payload = {
            "updated_at": now_jst.isoformat(),
            "count": len(out_dict),
            "articles": out_dict
        }
        os.makedirs(os.path.dirname(archive_path), exist_ok=True)
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [警告] アーカイブ保存失敗: {e}", file=sys.stderr)


def summarize_with_gemini(category_name, news_items, api_key, archive_cache):
    """Gemini API を呼び出して各記事の3行要約を生成（キャッシュヒット時はAPI呼び出しを節約）"""
    if not news_items:
        return []

    fallback_smart_summaries(category_name, news_items)

    uncached_indices = []
    for idx, item in enumerate(news_items):
        art_id = item["id"]
        cached = archive_cache.get(art_id)
        if cached and cached.get("is_ai_summary") and cached.get("headline") and cached.get("points"):
            item["headline"] = cached["headline"]
            item["points"] = cached["points"]
            item["takeaway"] = cached.get("takeaway", item["takeaway"])
            item["is_ai_summary"] = True
        else:
            uncached_indices.append(idx)

    if not uncached_indices:
        print(f"  -> 全 {len(news_items)} 件がアーカイブキャッシュから復元されました（APIコール節約）。")
        return news_items

    if not api_key:
        print("  -> APIキー未設定のため、インテリジェント要約エンジンを使用します。")
        return news_items

    articles_text = "\n\n".join([
        (
            f"【記事{pos + 1}】\n"
            f"見出し: {news_items[orig_idx]['title']}\n"
            f"配信元: {news_items[orig_idx]['source']} ({news_items[orig_idx]['pub_date']})\n"
            f"関連見出し・抜粋: {news_items[orig_idx]['description'] or '（見出しのみ）'}"
        )
        for pos, orig_idx in enumerate(uncached_indices)
    ])

    target_count = len(uncached_indices)
    prompt = f"""あなたは千葉県・首都圏の受験情報に精通した「進学塾のシニア受験アナリスト」です。
以下の【{category_name}】の最新ニュース全{target_count}件を読み解き、忙しい保護者・受験生および学習塾講師が朝の30秒で本質を把握できる3行要約を作成してください。

【対象記事】
{articles_text}

【厳守ルール】
1. 記事1から記事{target_count}まで全{target_count}件を1件も漏らさずJSON配列で出力してください。
2. 見出しの単なるオウム返し（「〜を詳しく解説している」「〜が発表された」だけの文）は厳禁です。見出しや関連抜粋に含まれる学校名・塾名・模試名・制度変更・日程・数値の核心と「なぜ今それが重要か（背景・位置づけ）」を具体的に記述してください。
3. 各フィールドの仕様:
   - index: 記事番号（1〜{target_count}の整数）
   - headline: カードの最上部に大きく表示する「30秒核心見出し」（22〜32文字程度。一番伝えたい結論を端的に）
   - points: 重要な事実・決定事項・入試への影響を2点（各40〜65文字程度。具体的な対象校や制度内容を明記）
   - takeaway: 塾講師が保護者面談・生徒指導でそのまま使える具体的なアドバイス、または家庭で今すぐ取るべき対策（45〜70文字程度。抽象的な精神論は避ける）"""

    response_schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "index": {"type": "INTEGER"},
                "headline": {"type": "STRING"},
                "points": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                },
                "takeaway": {"type": "STRING"}
            },
            "required": ["index", "headline", "points", "takeaway"]
        }
    }

    models_to_try = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-flash-latest"]

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema
            }
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key
                }
            )
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if not candidates:
                    continue
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                summaries = json.loads(text)
                if not isinstance(summaries, list):
                    continue

                applied_count = 0
                for s in summaries:
                    pos = s.get("index", 1) - 1
                    if 0 <= pos < len(uncached_indices):
                        orig_idx = uncached_indices[pos]
                        if s.get("headline"):
                            news_items[orig_idx]["headline"] = s["headline"].strip()
                        if s.get("points") and isinstance(s["points"], list):
                            news_items[orig_idx]["points"] = [str(p).strip() for p in s["points"] if str(p).strip()]
                        if s.get("takeaway"):
                            news_items[orig_idx]["takeaway"] = s["takeaway"].strip()
                        news_items[orig_idx]["is_ai_summary"] = True
                        applied_count += 1

                print(f"  -> Gemini API ({model}) で新規 {applied_count}/{target_count} 件の要約生成に成功！")
                return news_items
        except Exception as e:
            print(f"  -> Gemini API ({model}) 試行失敗: {e}", file=sys.stderr)
            continue

    print("  -> API未接続または失敗のため、インテリジェント要約エンジンの結果を使用します。")
    return news_items


def fallback_smart_summaries(category_name, news_items):
    """API未接続時でも、タイトルと関連抜粋から具体的な要約を合成する安全エンジン"""
    for item in news_items:
        t = item["title"]
        src = item["source"]
        desc = item.get("description", "")

        if re.search(r"(英検|英語検定|漢検|漢字検定|数検|数学検定|算数検定|英語入試)", t):
            match_cert = re.search(r"(英検|英語検定|漢検|漢字検定|数検|数学検定|算数検定|英語入試)", t)
            cert_name = match_cert.group(0) if match_cert else "外部検定"
            item["headline"] = f"{cert_name}の入試優遇・最新対策のポイント"
            item["points"] = [
                f"{src}にて「{t}」に関する具体的な動向・対策のポイントが報じられました。",
                desc if desc else f"{cert_name}のスコア・取得級を出願要件や学科試験の加点（みなし満点）に活用する学校が拡大しています。"
            ]
            item["takeaway"] = f"志望校の募集要項で{cert_name}の優遇基準（対象級・CSEスコア）を確認し、出願に間に合う検定日程を逆算して組み込みましょう。"

        elif re.search(r"(四谷大塚|合不合|組分け|Vもぎ|Sもぎ|進研|模試|偏差値|倍率|志願)", t):
            item["headline"] = f"最新模試・偏差値・志願倍率の注目動向"
            item["points"] = [
                f"「{t}」（{src}）が公開され、最新の志望者動向や目標偏差値の目安が示されました。",
                desc if desc else "千葉入試や首都圏本命校、公立・私立併願の出願戦略を固める上で重要な指標となります。"
            ]
            item["takeaway"] = "模試の偏差値や判定結果だけでなく、大問別の正答率データから「今すぐ埋めるべき基礎の穴」を特定して反復演習に繋げましょう。"

        elif re.search(r"(出願|日程|定員|募集|一般入学者選抜|入学者選抜|説明会|要項|選抜|発表|人員|10：0|10:0)", t):
            item["headline"] = f"入試日程・募集定員・出願手続きの重要情報"
            item["points"] = [
                f"「{t}」（{src}）に関するスケジュールや選抜要項の詳細が案内されています。",
                desc if desc else "Web出願の事前登録期間や必要書類（調査書等）の準備、併願パターン別の手続き締切日の確認が重要です。"
            ]
            item["takeaway"] = "出願開始日・締切日・合格発表後の手続き期限を親子・教室で共有し、カレンダーに書き込んでダブルチェックを行いましょう。"

        else:
            item["headline"] = t[:30] + ("…" if len(t) > 30 else "")
            item["points"] = [
                f"{src}による「{t}」の最新レポートです。",
                desc if desc else f"{category_name}における志望校選びや直前期の学習戦略に関わる重要トピックが取り上げられています。"
            ]
            item["takeaway"] = "最新の入試トレンドを踏まえつつ、志望校の過去問分析と日々の基礎定着をぶれずに継続していきましょう。"

    return news_items


def render_news_cards(news_items, category_name):
    """HTMLエスケープ済み・アクションボタン付きのカード群HTMLを生成"""
    if not news_items:
        return """
        <div class="empty-state">
            <div class="icon">📭</div>
            <p>現在表示できる新着ニュースはありません。<br>次回の自動更新をお待ちください。</p>
        </div>
        """

    html_cards = []
    for item in news_items:
        art_id = html.escape(item.get("id", ""), quote=True)
        source_esc = html.escape(item.get("source", ""), quote=True)
        pub_date_esc = html.escape(item.get("pub_date", ""), quote=True)
        title_esc = html.escape(item.get("title", ""), quote=True)
        headline_raw = item.get("headline") or item.get("title", "")
        headline_esc = html.escape(headline_raw, quote=True)
        link_esc = html.escape(item.get("link", "#"), quote=True)
        badge_label_esc = html.escape(item.get("badge_label", "💡注目"), quote=True)
        badge_cls_esc = html.escape(item.get("badge_cls", "badge-strategy"), quote=True)

        points = item.get("points", [])
        takeaway_raw = item.get("takeaway", "")

        points_html = "".join([
            f'<div class="summary-point"><span class="dot">•</span><span>{html.escape(str(p), quote=True)}</span></div>'
            for p in points
        ])

        takeaway_html = (
            f'<div class="summary-takeaway">💬 <strong>面談・対策ポイント:</strong> '
            f'{html.escape(takeaway_raw, quote=True)}</div>'
            if takeaway_raw else ""
        )

        new_badge_html = '<span class="badge-new">🔥 NEW</span>' if item.get("is_new") else ""

        # コピー・LINE共有用の整形テキスト
        copy_lines = [
            f"【{category_name}】{headline_raw}",
            f"📰 {item.get('title', '')}（{item.get('source', '')} / {item.get('pub_date', '')}）",
        ]
        for p in points:
            copy_lines.append(f"・{p}")
        if takeaway_raw:
            copy_lines.append(f"💡 ポイント: {takeaway_raw}")
        copy_lines.append(f"🔗 {item.get('link', '')}")
        copy_text_esc = html.escape("\n".join(copy_lines), quote=True)

        card = f"""
        <article class="news-card" data-article-id="{art_id}" data-is-new="{ 'true' if item.get('is_new') else 'false' }">
            <div class="card-header">
                <div class="card-badges">
                    {new_badge_html}
                    <span class="topic-badge {badge_cls_esc}">{badge_label_esc}</span>
                    <span class="card-source">{source_esc}</span>
                </div>
                <div class="card-meta-right">
                    <span class="read-indicator" title="既読">✓ 既読</span>
                    <span class="card-date">{pub_date_esc}</span>
                </div>
            </div>
            <h3 class="card-headline-main">{headline_esc}</h3>
            <p class="card-original-title">📰 元記事: {title_esc}</p>
            <div class="summary-box">
                <div class="summary-points">
                    {points_html}
                </div>
                {takeaway_html}
            </div>
            <div class="card-footer">
                <div class="card-actions">
                    <button type="button" class="btn-action btn-copy" data-copy="{copy_text_esc}" onclick="copySummary(this)" title="要約テキストをコピー">
                        <span>📋</span><span>要約コピー</span>
                    </button>
                    <button type="button" class="btn-action btn-share" data-copy="{copy_text_esc}" data-title="{headline_esc}" data-url="{link_esc}" onclick="shareArticle(this)" title="LINEや他アプリで共有">
                        <span>📤</span><span>共有</span>
                    </button>
                    <button type="button" class="btn-action btn-bookmark" data-article-id="{art_id}" onclick="toggleBookmark(this, '{art_id}')" title="あとで読む（保存）">
                        <span class="bm-icon">☆</span><span class="bm-text">保存</span>
                    </button>
                </div>
                <a href="{link_esc}" target="_blank" rel="noopener noreferrer" class="btn-read-more" onclick="markAsRead('{art_id}')">
                    <span>元記事</span>
                    <span>↗</span>
                </a>
            </div>
        </article>
        """
        html_cards.append(card)
    return "\n".join(html_cards)


def main():
    print("=== 受験ニュース要約 生成開始 ===")
    api_key = load_api_key()
    now_jst = datetime.now(JST)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "template.html")
    output_path = os.path.join(script_dir, "docs", "index.html")
    archive_path = os.path.join(script_dir, "docs", "archive.json")

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    archive_cache = load_archive(archive_path)
    global_seen_keys = set()
    global_seen_titles = []
    all_news = {}
    total_fetched = 0

    for cat in CATEGORIES:
        cat_id = cat["id"]
        print(f"[{cat['name']}] ニュース取得中...")
        items = fetch_rss_news(cat, now_jst, global_seen_keys, global_seen_titles, max_items=MAX_ITEMS_PER_CATEGORY)

        if not items and archive_cache:
            print(f"  [警告] RSSから取得できなかったため、アーカイブから {cat['name']} の直近記事を復元します。")
            cached_cat_items = [
                v for v in archive_cache.values()
                if v.get("category_id") == cat_id
            ]
            cached_cat_items.sort(key=lambda x: x.get("pub_ts", 0), reverse=True)
            items = cached_cat_items[:MAX_ITEMS_PER_CATEGORY]

        print(f"  -> {len(items)} 件取得（最新順ソート済み）。要約処理を実行中...")
        summarized_items = summarize_with_gemini(cat["name"], items, api_key, archive_cache)
        all_news[cat_id] = summarized_items
        total_fetched += len(summarized_items)

        for it in summarized_items:
            archive_cache[it["id"]] = it

        time.sleep(1)

    # 全カテゴリ合計が0件なら既存ファイルを保護
    if total_fetched == 0:
        print("🚨 [致命的エラー] 全カテゴリの取得ニュースが0件のため、docs/index.html の上書きを中止します。", file=sys.stderr)
        sys.exit(1)

    save_archive(archive_path, archive_cache, now_jst)

    updated_str = now_jst.strftime("%m月%d日 %H:%M")
    updated_iso = now_jst.strftime("%Y-%m-%d")

    junior_items = all_news.get("junior", [])
    high_items = all_news.get("high", [])
    univ_items = all_news.get("univ", [])

    rendered = template
    rendered = rendered.replace("{{UPDATED_TIME}}", updated_str)
    rendered = rendered.replace("{{UPDATED_DATE_ISO}}", updated_iso)
    rendered = rendered.replace("{{CURRENT_YEAR}}", str(now_jst.year))

    rendered = rendered.replace("{{JUNIOR_COUNT}}", str(len(junior_items)))
    rendered = rendered.replace("{{HIGH_COUNT}}", str(len(high_items)))
    rendered = rendered.replace("{{UNIV_COUNT}}", str(len(univ_items)))

    rendered = rendered.replace("{{JUNIOR_NEWS_CARDS}}", render_news_cards(junior_items, "中学受験"))
    rendered = rendered.replace("{{HIGH_NEWS_CARDS}}", render_news_cards(high_items, "高校受験"))
    rendered = rendered.replace("{{UNIV_NEWS_CARDS}}", render_news_cards(univ_items, "大学受験"))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"=== 生成完了: {output_path} (合計 {total_fetched} 件) ===")


if __name__ == "__main__":
    main()
