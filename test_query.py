import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json

queries = {
    "junior": "(千葉 OR 首都圏 OR 開成 OR 渋幕) 中学受験 OR 中学入試",
    "high": "(千葉 OR 首都圏 OR 県立高校) 高校受験 OR 公立高校入試",
    "univ": "(首都圏 OR 東京 OR 千葉 OR 共通テスト OR 早慶 OR MARCH) 大学受験 OR 大学入試"
}

for cat, q in queries.items():
    encoded = urllib.parse.quote(q)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ja&gl=JP&ceid=JP:ja"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            root = ET.fromstring(resp.read())
            items = root.findall(".//item")
            print(f"=== {cat} ({len(items)} items) ===")
            for item in items[:4]:
                title = item.find("title").text if item.find("title") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                print(f"Title: {title}")
                print(f"Desc snippet: {desc[:120]}...\n")
    except Exception as e:
        print(f"Error {cat}: {e}")
