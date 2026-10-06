# -*- coding: utf-8 -*-
# TVBox 播放源：影视大全（sounding.cc）
# 站点类型：苹果CMS V10（ThinkPHP 5.0，伪静态短路由 + stui 模板）
# 接口：homeContent / homeVideoContent / categoryContent / detailContent / searchContent / playerContent
# 站点特征（2026-09-15 实测）：
#   - 访问控制：普通 UA 直接 403（Cloudflare 校验）；Baiduspider 搜索引擎 UA 直接放行 200 → 插件固定使用 Baiduspider UA
#   - 分类入口 /vodtype/{tid}.html；分类列表 /vodtype/{tid}-{n}.html（每页 36 条，分页至尾页）
#   - 列表条目 a.stui-vodlist__thumb（href=/detail/{vid}.html, title=片名, data-original=海报, span.pic-text=备注）
#   - 详情页 /detail/{vid}.html：stui-content__detail 区含 片名/类型/地区/年份/状态/主演/导演/简介；
#     播放线路为多个独立 .stui-pannel（h3.title=线路名 + ul.stui-content__playlist > li > a[href=/vodplay/{vid}/{sid}/{nid}.html]=集名）
#   - 播放页 /vodplay/{vid}/{sid}/{nid}.html：内嵌 var player_aaaa={...} JSON，url 字段即 m3u8 直链（encrypt=0）
#   - 搜索：源站搜索接口已确认损坏——POST /vodsearch.html → 520；GET /index.php/vod/search.html?wd=、
#     伪静态 /vodsearch/{kw}.html 均忽略关键词（200 但返回与关键词无关的随机推荐列表）
#     → searchContent 直接返回空列表，避免输出错误结果
# 依赖：优先 requests；无 requests 环境自动降级 urllib 标准库
# 约定：类名必须为 Spider；playerContent(self, flag, ids, vipFlags="") 返回 {"parse": 0, "playUrl": "...", "header": "..."}

import re
import json
import sys

try:
    sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

try:
    import requests
except Exception:
    requests = None

import urllib.parse
import urllib.request

HOST = "sounding.cc"
# 站点按搜索引擎 UA 放行采集，固定为 Baiduspider
UA = "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)"
TIMEOUT = 15

# 首页菜单解析失败时的兜底分类（主分类 + 常用子分类）
CLASSES = [
    ("1", "电影"), ("2", "电视剧"), ("3", "综艺片"), ("4", "动漫"), ("24", "短剧"),
    ("6", "动作片"), ("7", "喜剧片"), ("8", "爱情片"), ("9", "科幻片"), ("10", "剧情片"),
    ("11", "战争片"), ("41", "动画片"), ("12", "记录片"), ("39", "恐怖片"),
    ("13", "国产剧"), ("14", "香港剧"), ("15", "韩国剧"), ("16", "欧美剧"), ("22", "台湾剧"),
    ("21", "日本剧"), ("20", "泰国剧"), ("23", "海外剧"),
    ("25", "大陆综艺"), ("26", "日韩综艺"), ("27", "港台综艺"), ("28", "欧美综艺"),
    ("29", "国产动漫"), ("30", "日本动漫"), ("42", "港台动漫"), ("31", "欧美动漫"), ("43", "海外动漫"),
    ("40", "短剧大全"), ("33", "穿越重生"), ("34", "反转爽剧"), ("35", "言情总裁"),
    ("36", "现代都市"), ("37", "古装仙侠"), ("38", "悬疑烧脑"),
]


class Spider(_BaseSpider):
    def __init__(self):
        self.host = HOST
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://%s/" % HOST,
        }
        self.session = requests.Session() if requests is not None else None
        if self.session is not None:
            self.session.headers.update(self.headers)

    # ---------- 可选能力 ----------

    def getName(self):
        return "影视大全"

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        return bool(url) and not url.startswith("http")

    def manualVideoCheck(self):
        pass

    # ---------- 内部工具 ----------

    def _url(self, path):
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return "https://%s%s" % (self.host, path)

    def _abs(self, s):
        s = (s or "").strip()
        if not s:
            return ""
        if s.startswith("//"):
            return "https:" + s
        if s.startswith("/"):
            return "https://%s%s" % (self.host, s)
        if s.startswith("http"):
            return s
        return "https://%s/%s" % (self.host, s)

    def _http_get(self, url, referer=None, timeout=TIMEOUT):
        hdrs = dict(self.headers)
        if referer:
            hdrs["Referer"] = referer
        # 站点存在偶发 403/520 限流抖动，失败自动重试 2 次
        last = None
        for attempt in range(3):
            try:
                if self.session is not None:
                    r = self.session.get(url, headers=hdrs, timeout=timeout)
                    if not r.ok:
                        raise RuntimeError("HTTP %s for %s" % (r.status_code, url))
                    try:
                        r.encoding = "utf-8"
                    except Exception:
                        pass
                    return r.text
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = resp.read()
                    m = re.search(rb"charset=[\"']?([\w-]+)", data[:3000], re.I)
                    enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
                    try:
                        return data.decode(enc, "ignore")
                    except (LookupError, ValueError):
                        return data.decode("utf-8", "ignore")
            except Exception as e:
                last = e
                if attempt < 2:
                    import time
                    time.sleep(0.8 * (attempt + 1))
        raise last if last else RuntimeError("request failed: %s" % url)

    def _get(self, path, referer=None, timeout=TIMEOUT):
        return self._http_get(self._url(path), referer=referer, timeout=timeout)

    @staticmethod
    def _clean(s):
        return re.sub(r"\s+", " ", s or "").strip()

    @staticmethod
    def _extract_js_object(text, start):
        """从 start 位置的 '{' 起做括号配对（正确处理字符串内括号），返回完整 JS 对象字面量。"""
        brace = text.find("{", start)
        if brace == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        for k in range(brace, len(text)):
            c = text[k]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return text[brace:k + 1]
        return None

    def _classes(self):
        """动态解析首页导航菜单，再以静态全量分类补全子分类，避免子菜单丢失。"""
        try:
            html = self._get("/")
        except Exception:
            html = ""
        out = []
        seen = set()
        for m in re.finditer(
            r'<a[^>]*href="/vodtype/(\d+)\.html"[^>]*>\s*([^<]{1,16})\s*</a>', html, re.S):
            tid, tname = m.group(1), self._clean(m.group(2))
            if tid in seen:
                continue
            seen.add(tid)
            out.append({"type_id": tid, "type_name": tname})
        for tid, tname in CLASSES:
            if tid in seen:
                continue
            seen.add(tid)
            out.append({"type_id": tid, "type_name": tname})
        return out

    def _parse_poster_list(self, html):
        """解析列表页/搜索页中的 stui-vodlist__thumb 卡片。"""
        out = []
        seen = set()
        for m in re.finditer(
            r'<a[^>]*class="stui-vodlist__thumb[^"]*"[^>]*href="([^"]*detail/(\d+)\.html)"'
            r'[^>]*title="([^"]*)"[^>]*data-original="([^"]*)"[^>]*>',
            html, re.S):
            url, vid, name, pic = m.groups()
            if vid in seen:
                continue
            seen.add(vid)
            rem = ""
            rm = re.search(re.escape(url) + r'.*?<span[^>]*class="pic-text[^"]*"[^>]*>([^<]*)<',
                           html[m.start():m.start() + 900], re.S)
            if rm:
                rem = self._clean(rm.group(1))
            out.append({
                "vod_id": vid,
                "vod_name": self._clean(name),
                "vod_pic": self._abs(pic),
                "vod_remarks": rem,
            })
        return out

    @staticmethod
    def _last_page(html, tid):
        """从分页链接取最大页数（/vodtype/{tid}-{n}.html）；无则 1。"""
        pages = [int(x) for x in re.findall(r'/vodtype/%s-(\d+)\.html' % re.escape(str(tid)), html)]
        return max(pages) if pages else 1

    @staticmethod
    def _field_row(seg, key):
        """从详情页原始 HTML 段按 '键：' 定位，截取到 </p> 前，去标签取文本。
        兼容两种形态：`<span>键：</span><a>值</a>` 与 `<span>键：值</span>`。
        """
        i = seg.find(key + "：")
        sep = 1
        if i == -1:
            i = seg.find(key + ":")
            sep = 2 if key in ("类型", "主演", "导演", "简介") else 1
        if i == -1:
            return ""
        tail = seg[i + len(key) + 1:]
        # 截断到行尾（</p> 等），先保留完整标签，再去标签，最后按文本中的下一个字段键截断
        tail = re.split(r"</p>|<p[\s>]|</h3>|<div", tail)[0]
        tail = re.sub(r"<[^>]+>", "", tail)
        tail = re.sub(r"&nbsp;", " ", tail)
        tail = re.split(r"(?:类型|地区|年份|状态|主演|导演|简介)[：:]", tail)[0]
        v = re.sub(r"\s+", "", tail).strip("：:|｜")
        if not v or v.startswith(("立即播放", "播放地址", "查看")):
            return ""
        return v[:200]

    def _detail(self, vid):
        url = "/detail/%s.html" % vid
        try:
            html = self._get(url)
        except Exception:
            return {}

        detail = {
            "vod_id": str(vid),
            "vod_name": "",
            "vod_pic": "",
            "vod_actor": "",
            "vod_director": "",
            "vod_remarks": "",
            "vod_content": "",
            "vod_year": "",
            "vod_area": "",
            "vod_class": "",
        }

        # 片名 / 信息区位于 stui-content__detail 区块（字段值可能在 <a> 内）
        m = re.search(r'<div class="stui-content__detail[^"]*"[^>]*>(.*?)(?:立即播放|<!-- end 详细信息)',
                      html, re.S)
        if m:
            seg = m.group(1)
            tm = re.search(r'<h3[^>]*class="title"[^>]*>\s*([^<]{1,80}?)\s*</h3>', seg)
            if tm:
                detail["vod_name"] = self._clean(tm.group(1))
            detail["vod_class"] = self._field_row(seg, "类型")
            detail["vod_area"] = self._field_row(seg, "地区")
            detail["vod_year"] = self._field_row(seg, "年份")
            detail["vod_remarks"] = self._field_row(seg, "状态")
            detail["vod_actor"] = self._field_row(seg, "主演")
            detail["vod_director"] = self._field_row(seg, "导演")
            detail["vod_content"] = self._field_row(seg, "简介")
        # 封面
        m = re.search(r'<div class="stui-content__thumb[^"]*"[^>]*>.*?data-original="([^"]+)"',
                      html, re.S)
        if m:
            detail["vod_pic"] = self._abs(m.group(1))
        # 剧情简介（stui-content__desc 块优先，信息区"简介："为 SEO 短文案）
        m = re.search(r'<div class="stui-content__desc[^"]*"[^>]*>(.*?)</div>', html, re.S)
        if m:
            desc = self._clean(re.sub(r"<[^>]+>", "", m.group(1)))
            desc = desc.replace("&nbsp;", " ").strip()
            if desc:
                detail["vod_content"] = desc
        detail["vod_content"] = (detail.get("vod_content") or "").replace("&nbsp;", " ").strip()

        # 播放线路：多个 .stui-pannel（h3.title=线路名 + ul.stui-content__playlist=选集）
        play_from = []
        play_urls = []
        for m in re.finditer(
            r'<h3 class="title">\s*([^<]{1,40}?)\s*</h3>.*?<ul class="stui-content__playlist[^"]*"[^>]*>(.*?)</ul>',
            html, re.S):
            line_name = self._clean(m.group(1))
            if not line_name or line_name in ("剧情介绍", "观众心声", "相关推荐", "大家都在搜"):
                continue
            eps = re.findall(
                r'<a[^>]*href="(/vodplay/\d+/\d+/\d+\.html)"[^>]*>([^<]*)</a>', m.group(2))
            if not eps:
                continue
            src = line_name
            if src in play_from:
                src = src + str(len(play_from))
            play_from.append(src)
            play_urls.append("#".join(
                "%s$%s" % (self._clean(ep[1]), self._url(ep[0])) for ep in eps))

        if play_from and play_urls:
            detail["vod_play_from"] = "$$$".join(play_from)
            detail["vod_play_url"] = "$$$".join(play_urls)
        return detail

    # ---------- 标准接口 ----------

    def init(self, extend=""):
        if not extend:
            return
        host = None
        s = extend.strip()
        if s.startswith("{"):
            try:
                host = (json.loads(s) or {}).get("host")
            except Exception:
                host = None
        if not host:
            m = re.search(r"(?:host|url)\s*[=:]\s*([^\s\"']+)", extend)
            if m:
                host = m.group(1).strip()
        if host:
            host = str(host).replace("https://", "").replace("http://", "").rstrip("/")
            if host:
                self.host = host

    def homeContent(self, filter=False):
        return {
            "class": self._classes(),
            "list": [],
            "filters": {},
        }

    def homeVideoContent(self):
        try:
            html = self._get("/vodtype/1.html")
        except Exception:
            return {"list": []}
        lst = self._parse_poster_list(html)
        return {"list": lst[:40]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        if not isinstance(pg, int):
            try:
                pg = int(pg or 1)
            except Exception:
                pg = 1
        if pg < 1:
            pg = 1
        path = "/vodtype/%s-%s.html" % (tid, pg)
        try:
            html = self._get(path)
        except Exception:
            return {"page": pg, "pagecount": 1, "limit": 36, "total": 0, "list": []}
        lst = self._parse_poster_list(html)
        total_page = self._last_page(html, tid)
        total = len(lst) if total_page == 1 else total_page * 36
        return {"page": pg, "pagecount": total_page, "limit": 36, "total": total, "list": lst}

    def detailContent(self, ids):
        if isinstance(ids, list):
            ids = ids[0] if ids else ""
        m = re.search(r"(\d+)", str(ids))
        if not m:
            return {"list": []}
        detail = self._detail(m.group(1))
        return {"list": [detail]} if detail else {"list": []}

    def searchContent(self, key, quick=False, pg=1):
        """源站搜索接口已损坏（见文件头注释）：所有通道均忽略关键词返回随机推荐。
        为避免在播放器中展示错误搜索结果，直接返回空列表。
        """
        return {"list": []}

    def playerContent(self, flag, ids, vipFlags=""):
        url = self._url(str(ids))
        try:
            html = self._get(url)
        except Exception:
            return {}
        # player_aaaa = {...} JSON：括号配对截取，url 字段为 m3u8 直链
        m = re.search(r'player_aaaa\s*=\s*(\{)', html)
        data = None
        if m:
            obj = self._extract_js_object(html, m.start(1))
            if obj:
                try:
                    data = json.loads(obj)
                except Exception:
                    data = None
        if not data:
            m2 = re.search(r'"url"\s*:\s*"([^"]+)"', html)
            if m2:
                play = m2.group(1)
                if play.startswith("//"):
                    play = "https:" + play
                return {"parse": 1, "playUrl": play, "header": "Referer: %s" % self._url("/")}
            return {}
        raw = data.get("url") or ""
        play = raw.strip()
        if play.startswith("//"):
            play = "https:" + play
        if re.search(r"\.(m3u8|mp4|flv)(\?|$)", play, re.I):
            return {"parse": 0, "playUrl": play, "header": "Referer: %s" % self._url("/")}
        if play.startswith("http"):
            return {"parse": 1, "playUrl": play, "header": "Referer: %s" % self._url("/")}
        if "/vodplay/" in url:
            return {"parse": 1, "playUrl": url, "header": "Referer: %s" % self._url("/")}
        return {}

    def destroy(self):
        try:
            if self.session is not None:
                self.session.close()
        except Exception:
            pass