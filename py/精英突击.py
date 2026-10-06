# -*- coding: utf-8 -*-
# 精英突击视频 jyhorizongridhub.live - MacCMS 站源
# type: /index.php/vod/type/id/{id}.html
# play: /index.php/vod/play/id/{id}/sid/1/nid/1.html
# player_aaaa.url = m3u8 直链

import gzip
import json
import re
import time
import urllib.parse
import urllib.request
from html import unescape as _unesc

BASE = "https://jyhorizongridhub.live"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

CLASSES = [
    {"type_id": "33", "type_name": "日本无码"},
    {"type_id": "35", "type_name": "字幕剧情"},
    {"type_id": "39", "type_name": "欧美视频"},
    {"type_id": "37", "type_name": "黑人视频"},
    {"type_id": "53", "type_name": "传媒拍摄"},
    {"type_id": "47", "type_name": "萝莉少女"},
    {"type_id": "31", "type_name": "捆绑调教"},
    {"type_id": "55", "type_name": "三级伦理"},
    {"type_id": "25", "type_name": "重口猎奇"},
    {"type_id": "59", "type_name": "卡通视频"},
    {"type_id": "43", "type_name": "直男色情"},
    {"type_id": "23", "type_name": "女同性恋"},
    {"type_id": "29", "type_name": "人妖色情"},
    {"type_id": "21", "type_name": "男同性恋"},
]

_CACHE = {}
_CACHE_CAP = 200
_TTL = 600


def _get(url, referer=None, retry=2, timeout=15, allow_cache=True):
    key = url
    now = time.time()
    if allow_cache and key in _CACHE and now - _CACHE[key][1] < _TTL:
        return _CACHE[key][0]
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    text = ""
    for attempt in range(retry + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if enc == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", "ignore")
                break
        except Exception:
            if attempt < retry:
                time.sleep(0.4)
    if text:
        if len(_CACHE) >= _CACHE_CAP:
            _CACHE.clear()
        _CACHE[key] = (text, time.time())
    return text


def _abs(u):
    if not u:
        return ""
    u = u.strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return BASE + u
    if u.startswith("http"):
        return u
    return BASE + "/" + u.lstrip("./")


def _clean(raw):
    if not raw:
        return ""
    t = re.sub(r"<[^>]+>", "", raw)
    t = _unesc(t)
    return re.sub(r"\s+", " ", t).strip()


def isVideoFormat(url):
    if not url or not isinstance(url, str):
        return False
    path = url.lower().split("?")[0].split("#")[0]
    return bool(re.search(r"\.(m3u8|mp4|mkv|flv|ts|webm)$", path))


def _cards(html, limit=36):
    cards = []
    seen = set()
    # data-post_id + duration + title link + img
    for m in re.finditer(
        r'data-post_id="(\d+)"[^>]*data-post_duration="(\d+)"[\s\S]{0,800}?'
        r'href="(/index\.php/vod/play/id/(\d+)/sid/\d+/nid/\d+\.html)"[\s\S]{0,400}?'
        r'(?:src|data-src|data-original)="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        html,
        re.I,
    ):
        post_id, dur, href, vid, pic = m.groups()
        if vid in seen:
            continue
        seen.add(vid)
        # title from nearby
        block = html[max(0, m.start() - 100) : m.end() + 100]
        title = ""
        tm = re.search(
            r'href="/index\.php/vod/play/id/%s[^"]*"[^>]*>\s*(?:<[^>]+>)*([^<]{2,80})'
            % vid,
            block,
        )
        if tm:
            title = _clean(tm.group(1))
        if not title:
            tm = re.search(r"<font[^>]*>\s*([^<]{2,80})\s*</font>", block)
            if tm:
                title = _clean(tm.group(1))
        if not title:
            title = "视频" + vid
        # duration format
        try:
            sec = int(dur)
            remarks = "%d:%02d" % (sec // 60, sec % 60) if sec else ""
        except Exception:
            remarks = ""
        cards.append(
            {
                "vod_id": _abs(href),
                "vod_name": title,
                "vod_pic": _abs(pic),
                "vod_remarks": remarks,
            }
        )
        if len(cards) >= limit:
            break
    # fallback simpler
    if not cards:
        for m in re.finditer(
            r'href="(/index\.php/vod/play/id/(\d+)/sid/\d+/nid/\d+\.html)"[\s\S]{0,300}?>'
            r"([\s\S]{0,100}?)</a>",
            html,
        ):
            href, vid, raw_t = m.group(1), m.group(2), m.group(3)
            if vid in seen:
                continue
            seen.add(vid)
            title = _clean(raw_t)
            if not title or len(title) < 2:
                continue
            cards.append(
                {
                    "vod_id": _abs(href),
                    "vod_name": title,
                    "vod_pic": "",
                    "vod_remarks": "",
                }
            )
            if len(cards) >= limit:
                break
    return cards


def _pager(html, page):
    nums = [int(x) for x in re.findall(r"/page/(\d+)\.html", html)]
    return max(nums) if nums else int(page)


def homeContent(filter=False):
    classes = [dict(c) for c in CLASSES]
    html = _get(BASE + "/")
    cards = _cards(html)[:20] if html else []
    return {"class": classes, "filters": {}, "list": cards}


def homeVideoContent():
    html = _get(BASE + "/")
    return _cards(html)[:20] if html else []


def categoryContent(tid, pg="1", filter="", extend=""):
    try:
        page = max(1, int(pg))
    except Exception:
        page = 1
    tid = str(tid or "").strip()
    if not tid:
        return {"list": [], "page": 1, "pagecount": 1, "limit": 36, "total": 0}
    if page == 1:
        url = BASE + "/index.php/vod/type/id/%s.html" % tid
    else:
        url = BASE + "/index.php/vod/type/id/%s/page/%d.html" % (tid, page)
    html = _get(url, referer=BASE + "/")
    if not html:
        return {"list": [], "page": page, "pagecount": 1, "limit": 36, "total": 0}
    cards = _cards(html)
    pagecount = _pager(html, page)
    return {
        "list": cards,
        "page": page,
        "pagecount": pagecount,
        "limit": 36,
        "total": pagecount * 36,
    }


def detailContent(ids, flags=None):
    if not ids:
        return {"list": []}
    vid = ids[0] if isinstance(ids, (list, tuple)) else ids
    vid = str(vid)
    if not vid.startswith("http"):
        vid = _abs(vid)
    # 若已是 play 页，直接用；否则从 id 构造
    if "/vod/play/id/" not in vid:
        mid = re.search(r"/id/(\d+)", vid) or re.search(r"(\d+)", vid)
        if mid:
            vid = BASE + "/index.php/vod/play/id/%s/sid/1/nid/1.html" % mid.group(1)
        else:
            return {"list": []}

    html = _get(vid, referer=BASE + "/", allow_cache=False)
    if not html:
        return {"list": []}

    title = ""
    m = re.search(r'"vod_name"\s*:\s*"([^"]+)"', html)
    if m:
        try:
            title = json.loads('"%s"' % m.group(1))
        except Exception:
            title = _clean(m.group(1))
    if not title:
        og = re.search(r'property="og:title"\s+content="([^"]+)"', html)
        if og:
            title = _clean(og.group(1))
    if not title:
        tt = re.search(r"<title>([\s\S]*?)</title>", html)
        if tt:
            title = _clean(tt.group(1)).split("-")[0].strip()

    pic = ""
    ogi = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    if ogi:
        pic = ogi.group(1)

    play = ""
    m = re.search(r'"url"\s*:\s*"(https?:\\?/\\?/[^"]+)"', html)
    if m:
        play = m.group(1).replace("\\/", "/")
    if not play:
        m = re.search(r'var player_aaaa=\{[^}]*"url"\s*:\s*"([^"]+)"', html)
        if m:
            play = m.group(1).replace("\\/", "/")

    vod = {
        "vod_id": vid,
        "vod_name": title or "视频",
        "vod_pic": _abs(pic),
        "vod_year": "",
        "vod_area": "",
        "vod_director": "",
        "vod_remarks": "",
        "vod_content": title,
        "vod_actor": "",
        "vod_play_from": "直链",
        "vod_play_url": "正片$" + (play if play else vid),
    }
    return {"list": [vod]}


def searchContent(key, quick=False, pg="1"):
    kw = (key or "").strip()
    if not kw:
        return {"list": []}
    try:
        page = max(1, int(pg))
    except Exception:
        page = 1
    q = urllib.parse.quote(kw)
    if page == 1:
        url = BASE + "/index.php/vod/search/wd/%s.html" % q
    else:
        url = BASE + "/index.php/vod/search/wd/%s/page/%d.html" % (q, page)
    html = _get(url, referer=BASE + "/")
    if not html:
        return {"list": [], "page": page, "pagecount": 1, "limit": 36, "total": 0}
    cards = _cards(html)
    return {
        "list": cards,
        "page": page,
        "pagecount": _pager(html, page),
        "limit": 36,
        "total": len(cards),
    }


def playerContent(flag, id, vipFlags=None):
    if not id:
        return {"parse": 1, "playUrl": "", "url": "", "header": ""}
    vid = str(id)
    if isVideoFormat(vid):
        return {
            "parse": 0,
            "playUrl": "",
            "url": vid,
            "header": json.dumps({"User-Agent": UA, "Referer": BASE + "/"}),
        }
    play_url = vid if vid.startswith("http") else _abs(vid)
    html = _get(play_url, referer=BASE + "/", allow_cache=False, retry=3)
    if not html:
        return {"parse": 1, "playUrl": play_url, "url": play_url, "header": ""}
    play = ""
    m = re.search(r'"url"\s*:\s*"(https?:\\?/\\?/[^"]+\.m3u8[^"]*)"', html)
    if m:
        play = m.group(1).replace("\\/", "/")
    if not play:
        m = re.search(r'"url"\s*:\s*"(https?:\\?/\\?/[^"]+)"', html)
        if m:
            play = m.group(1).replace("\\/", "/")
    if not play:
        m = re.search(r'(https?://[^"\']+\.m3u8[^"\']*)', html)
        if m:
            play = m.group(1)
    if not play:
        return {"parse": 1, "playUrl": play_url, "url": play_url, "header": ""}
    header = json.dumps({"User-Agent": UA, "Referer": BASE + "/"})
    return {"parse": 0, "playUrl": "", "url": play, "header": header}


def localProxy(param):
    return {"url": "", "header": ""}


try:
    from base.spider import Spider as _SpiderBase
except ImportError:
    class _SpiderBase(object):
        def homeContent(self, *a, **k):
            return {}
        def homeVideoContent(self, *a, **k):
            return []
        def categoryContent(self, *a, **k):
            return {}
        def detailContent(self, *a, **k):
            return {"list": []}
        def searchContent(self, *a, **k):
            return {"list": []}
        def playerContent(self, *a, **k):
            return {}
        def localProxy(self, param):
            return {"url": "", "header": ""}


class Spider(_SpiderBase):
    def init(self, extend=""):
        return "init"

    def getName(self):
        return "精英突击"

    def homeContent(self, filter=False):
        return homeContent(filter)

    def homeVideoContent(self):
        return homeVideoContent()

    def categoryContent(self, tid, pg="1", filter="", extend=""):
        return categoryContent(tid, pg, filter, extend)

    def detailContent(self, ids, flags=None):
        return detailContent(ids, flags)

    def searchContent(self, key, quick=False, pg="1"):
        return searchContent(key, quick, pg)

    def playerContent(self, flag, id, vipFlags=None):
        return playerContent(flag, id, vipFlags)

    def localProxy(self, param):
        return localProxy(param)

    def isVideoFormat(self, url):
        return isVideoFormat(url)

    def destroy(self):
        return None
