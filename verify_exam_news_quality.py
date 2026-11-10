#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受験ニュース スロット完全性・品質・Ragebait除外テスト"""
import os, sys, json, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, "docs", "data", "archive")
HTML_PATH = os.path.join(SCRIPT_DIR, "docs", "index.html")

RAGEBAIT_CHECK_REGEX = re.compile(
    r"([!?！？]{2,}|落ちる子の親|受かる子の親|受からない子|絶対不合格|不合格確定|人生終了|人生詰む|末路|悲惨|大惨事|地獄|絶望|破滅|崩壊|Fラン|ネット(?:騒然|炎上|激怒)|批判殺到|悲報)"
)

def test_exam_quality():
    print("=== [QA Test] 受験ニュース スロット完全性・品質テスト開始 ===")
    errors = []

    json_files = sorted([f for f in os.listdir(ARCHIVE_DIR) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", f)], reverse=True)
    if not json_files:
        sys.exit("❌ FAIL: アーカイブJSONが存在しません")

    with open(os.path.join(ARCHIVE_DIR, json_files[0]), "r", encoding="utf-8") as f:
        data = json.load(f)

    categories = data.get("categories", {})
    expected_cats = ["junior", "high", "univ"]
    total_news = 0

    for cid in expected_cats:
        if cid not in categories:
            errors.append(f"カテゴリ '{cid}' が存在しません")
            continue
        cdata = categories[cid]
        report = cdata.get("report")
        if not report or not report.get("summary"):
            errors.append(f"[{cid}] AI調査レポートが空です")
        news = cdata.get("news", [])
        cnt = len(news)
        total_news += cnt
        if cnt == 0:
            errors.append(f"[{cid}] 記事数が 0 件です（枠割れ）")
        for n in news:
            t = n.get("title", "")
            if RAGEBAIT_CHECK_REGEX.search(t):
                errors.append(f"[{cid}] 悪質煽りタイトル混入: '{t}'")

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    cards = len(re.findall(r'<article class="[^"]*news-card', html))
    if cards == 0:
        errors.append("HTML内の news-card が 0 件です")
    unreplaced = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if unreplaced:
        errors.append(f"HTML内に未置換テンプレート変数残存: {set(unreplaced)}")

    if errors:
        sys.exit("❌ テスト失敗:\n" + "\n".join("  - " + e for e in errors))
    print(f"✅ [ALL PASS] 最新日({json_files[0]}) 全3カテゴリのAIレポート・計{total_news}枠・Ragebait混入0件を確認しました！")

if __name__ == "__main__":
    test_exam_quality()
