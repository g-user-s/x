#!/usr/bin/env python3
"""Bir X (Twitter) postunun metnini ve resimlerini indirir; yapay zekanın okuyabileceği
Markdown + JSON olarak kaydeder.

Kullanım:
    pip install requests
    python fetch_tweet.py "https://x.com/kullanici/status/1234567890"

Kaynaklar (sırayla denenir, giriş/API anahtarı gerekmez):
    1. api.fxtwitter.com   2. api.vxtwitter.com   3. cdn.syndication.twimg.com
"""
import json
import math
import re
import sys
from pathlib import Path

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tweet-fetcher/1.0)"}
TIMEOUT = 20


def tweet_id(url: str) -> str:
    m = re.search(r"/status(?:es)?/(\d+)", url) or re.fullmatch(r"(\d+)", url.strip())
    if not m:
        sys.exit(f"Geçersiz post linki: {url}")
    return m.group(1)


def from_fxtwitter(tid):
    r = requests.get(f"https://api.fxtwitter.com/status/{tid}", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    t = r.json()["tweet"]
    media = (t.get("media") or {}).get("all") or []
    return {
        "id": tid,
        "author": t["author"]["screen_name"],
        "author_name": t["author"].get("name"),
        "date": t.get("created_at"),
        "text": t.get("text", ""),
        "images": [m["url"] for m in media if m.get("type") == "photo"],
        "videos": [m["url"] for m in media if m.get("type") in ("video", "gif")],
        "quote": (t.get("quote") or {}).get("text"),
        "source": "fxtwitter",
    }


def from_vxtwitter(tid):
    r = requests.get(f"https://api.vxtwitter.com/i/status/{tid}", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    t = r.json()
    media = t.get("media_extended") or []
    return {
        "id": tid,
        "author": t.get("user_screen_name"),
        "author_name": t.get("user_name"),
        "date": t.get("date"),
        "text": t.get("text", ""),
        "images": [m["url"] for m in media if m.get("type") == "image"],
        "videos": [m["url"] for m in media if m.get("type") in ("video", "gif")],
        "quote": (t.get("qrt") or {}).get("text"),
        "source": "vxtwitter",
    }


def _syndication_token(tid: str) -> str:
    # Twitter'ın embed widget'ının kullandığı token hesabı
    n = (int(tid) / 1e15) * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    whole, frac = int(n), n - int(n)
    out = ""
    while whole:
        out = digits[whole % 36] + out
        whole //= 36
    for _ in range(12):
        frac *= 36
        out += digits[int(frac)]
        frac -= int(frac)
    return re.sub(r"(0+|\.)", "", out) or "0"


def from_syndication(tid):
    r = requests.get(
        "https://cdn.syndication.twimg.com/tweet-result",
        params={"id": tid, "token": _syndication_token(tid), "lang": "en"},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    t = r.json()
    media = t.get("mediaDetails") or []
    videos = []
    for m in media:
        variants = (m.get("video_info") or {}).get("variants") or []
        mp4 = [v for v in variants if v.get("content_type") == "video/mp4"]
        if mp4:
            videos.append(max(mp4, key=lambda v: v.get("bitrate", 0))["url"])
    return {
        "id": tid,
        "author": t["user"]["screen_name"],
        "author_name": t["user"].get("name"),
        "date": t.get("created_at"),
        "text": t.get("text", ""),
        "images": [m["media_url_https"] for m in media if m.get("type") == "photo"],
        "videos": videos,
        "quote": (t.get("quoted_tweet") or {}).get("text"),
        "source": "syndication",
    }


def fetch(tid):
    errors = []
    for fn in (from_fxtwitter, from_vxtwitter, from_syndication):
        try:
            return fn(tid)
        except Exception as e:  # sonraki kaynağı dene
            errors.append(f"{fn.__name__}: {e}")
    sys.exit("Post alınamadı:\n  " + "\n  ".join(errors))


def save(data, out_root="output"):
    out = Path(out_root) / data["id"]
    out.mkdir(parents=True, exist_ok=True)

    local_images = []
    for i, url in enumerate(data["images"], 1):
        if "pbs.twimg.com" in url and "name=" not in url:
            url += ("&" if "?" in url else "?") + "name=orig"
        ext = re.search(r"\.(jpg|jpeg|png|webp|gif)", url)
        ext = ext.group(1) if ext else "jpg"
        path = out / f"image_{i}.{ext}"
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        path.write_bytes(r.content)
        local_images.append(path.name)
    data["local_images"] = local_images

    (out / "tweet.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# @{data['author']} ({data.get('author_name') or ''})", ""]
    if data.get("date"):
        md += [f"Tarih: {data['date']}", ""]
    md += [data["text"], ""]
    if data.get("quote"):
        md += ["> Alıntılanan post:", "> " + data["quote"].replace("\n", "\n> "), ""]
    md += [f"![resim {i}]({name})" for i, name in enumerate(local_images, 1)]
    md += [f"Video: {v}" for v in data["videos"]]
    (out / "tweet.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    data = fetch(tweet_id(sys.argv[1]))
    out = save(data)
    print(f"Kaynak: {data['source']}  |  {len(data['local_images'])} resim  ->  {out}/")
    print("-" * 40)
    print(data["text"])
