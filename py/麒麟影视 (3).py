"""
导航:   https://www.qiushui.vip   
           https://www.qiushuitv.cn
           https://www.qiushuiying.cn
由「影视py源生成器」自动生成 2026-09-15 15:22
站点: https://www.qlys.cc
接口: https://www.qlys.cc/api.php/provide/vod/
"""
import json
import re
import time
from urllib.parse import quote, urlencode, urljoin

import requests

try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    class _BaseSpider(object):
        """脱离影视壳独立运行时的占位基类，便于本地自检"""


class Spider(_BaseSpider):
    name = "麒麟影视"
    base_url = "https://www.qlys.cc"
    site_url = "https://www.qlys.cc"
    api_url = "https://www.qlys.cc/api.php/provide/vod/"

    class_name = ['电影', '电视剧', '短剧', '动漫', '综艺', '漫剧', '有声漫剧']
    class_url = ['1', '2', '3', '4', '5', '23', '24']

    _children = {'2': ['6', '7', '8', '9', '22'], '1': ['10', '11', '12', '13', '14', '15', '16', '17'], '4': ['18', '19', '20', '21']}

    prefix = "/index.php"
    _filter_mode = ''
    _filter_data = {}
    _filter_names = {
        "class": "类型", "area": "地区", "lang": "语言",
        "year": "年份", "letter": "字母", "by": "排序",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.qlys.cc/",
    }
    timeout = 15

    _session = None

    def getName(self):
        return self.name

    def init(self, extend=""):
        return ""

    def getHeaders(self):
        return self.headers

    def _get_session(self):
        if self._session is None:
            s = requests.Session()
            s.trust_env = False
            s.headers.update(self.headers)
            self._session = s
        return self._session

    def _api(self, **params):
        params = {k: v for k, v in params.items() if v not in ("", None)}
        url = self.api_url + ("&" if "?" in self.api_url else "?") + urlencode(params)
        for i in range(2):
            try:
                r = self._get_session().get(url, timeout=self.timeout)
                if r.status_code == 200 and r.text:
                    return r.json()
            except Exception as e:
                print(f"[{self.name}] 接口请求异常({i + 1}/2): {url} -> {e}")
                time.sleep(0.3)
        return None

    @staticmethod
    def _brief(item):
        return {
            "vod_id": str(item.get("vod_id", "")),
            "vod_name": item.get("vod_name", ""),
            "vod_pic": item.get("vod_pic", "") or item.get("vod_pic_thumb", ""),
            "vod_remarks": item.get("vod_remarks", ""),
            "vod_year": str(item.get("vod_year", "") or ""),
        }

    def homeContent(self, filter=False):
        result = {"class": [{"type_id": t, "type_name": n}
                            for t, n in zip(self.class_url, self.class_name)],
                  "filters": self._build_filters() if self._filter_mode else {}, "list": []}
        data = self._api(ac="list")
        if data and data.get("list"):
            result["list"] = [self._brief(x) for x in data["list"][:30]]
        return result

    def homeVideoContent(self):
        return self.homeContent()

    def categoryContent(self, tid, pg, filter=False, extend=None, content=None):
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        result = {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
        tid = str(tid)
        ext = self._ext_dict(extend, content)
        children = self._children.get(tid)
        if children:
            items, pagecount = [], 1
            for cid in children:
                data = self._api(ac="videolist", t=cid, pg=page)
                if not data:
                    continue
                items.extend(self._brief(x) for x in (data.get("list") or []))
                try:
                    pagecount = max(pagecount, int(data.get("pagecount") or 1))
                except Exception:
                    pass
            result["list"] = items[:60]
            result["pagecount"] = pagecount
            result["total"] = len(items)
            return result
        dims = self._filter_data.get(tid) or {}
        ext = {k: str(v) for k, v in ext.items()
               if str(v) and k in dims and str(v) != dims[k][0][1]}
        if ext and self._filter_mode == "api":
            data = self._api(ac="videolist", t=tid, pg=page, **ext)
            if data and data.get("list"):
                result["list"] = [self._brief(x) for x in data["list"]]
                result["total"] = int(data.get("total") or 0)
                try:
                    result["pagecount"] = int(data.get("pagecount") or 1)
                except Exception:
                    result["pagecount"] = 1
                return result
        if ext and self._filter_mode == "html":
            html = self._get_html(self._build_show_url(tid, page, ext))
            items = self._regex_cards(html, limit=60) if html else []
            if items:
                result["list"] = items
                result["total"] = len(items)
                maxpg = 0
                for m in re.finditer(r"/page/(\d+)\.html", html):
                    maxpg = max(maxpg, int(m.group(1)))
                result["pagecount"] = (maxpg if maxpg > page
                                        else (page + 1 if len(items) >= 60 else page))
                return result
        data = self._api(ac="videolist", t=tid, pg=page)
        if data and data.get("list"):
            result["list"] = [self._brief(x) for x in data["list"]]
            result["total"] = int(data.get("total") or 0)
            try:
                result["pagecount"] = int(data.get("pagecount") or 1)
            except Exception:
                result["pagecount"] = 1
        return result


    def _build_filters(self):
        filters = {}
        for tid, dims in self._filter_data.items():
            arr = []
            for param in ("class", "area", "lang", "year", "letter", "by"):
                if param not in dims:
                    continue
                arr.append({
                    "key": param,
                    "name": self._filter_names.get(param, param),
                    "init": "",
                    "value": [{"n": label, "v": val} for label, val in dims[param]],
                })
            if arr:
                filters[tid] = arr
        return filters

    @staticmethod
    def _ext_dict(extend, content=None):
        ext = extend if extend is not None else content
        if isinstance(ext, str) and ext:
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        return ext if isinstance(ext, dict) else {}

    def _build_show_url(self, tid, pg, extend):
        """苹果CMS筛选页路径：{prefix}/vod/show/by/../area/../class/../id/{tid}/lang/../year/../letter/../page/{pg}.html"""
        ext = extend or {}
        by = ext.get("by", "")
        area = ext.get("area", "")
        cls = ext.get("class", "")
        lang = ext.get("lang", "")
        year = ext.get("year", "")
        letter = ext.get("letter", "")
        path = f"{self.prefix}/vod/show/"
        if by:
            path += f"by/{by}/"
        if area:
            path += "area/%s/" % quote(str(area))
        if cls:
            path += "class/%s/" % quote(str(cls))
        path += "id/%s" % tid
        if lang:
            path += "/lang/%s" % quote(str(lang))
        if year:
            path += "/year/%s" % quote(str(year))
        if letter:
            path += "/letter/%s" % quote(str(letter))
        if pg and int(pg) > 1:
            path += "/page/%s.html" % pg
        else:
            path += ".html"
        return self.base_url + path

    def _get_html(self, url):
        try:
            r = self._get_session().get(url, timeout=self.timeout)
            if r.status_code == 200 and r.content:
                r.encoding = "utf-8"
                return r.text
        except Exception as e:
            print(f"[{self.name}] 筛选页请求异常: {url} -> {e}")
        return ""

    def _regex_cards(self, html, limit=60):
        """无 bs4 的通用卡片提取：用于筛选页解析"""
        items, seen = [], set()
        anchors = list(re.finditer(
            r'<a[^>]+href="[^"]*?/vod/detail/id/(\d+)\.html[^"]*"[^>]*>', html, re.I))
        for i, m in enumerate(anchors):
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            end = anchors[i + 1].start() if i + 1 < len(anchors) \
                else min(len(html), m.end() + 1500)
            block = html[m.start():end]
            seg = m.group(0)
            t = re.search(r'title="([^"]+)"', seg) or re.search(r'title="([^"]+)"', block)
            name = t.group(1).strip() if t else ""
            if not name:
                t2 = re.search(r'alt="([^"]+)"', block)
                name = t2.group(1).strip() if t2 else ""
            if not name:
                continue
            pic = ""
            pm = re.search(r'<img[^>]+(?:data-src|data-original|data-background|src)="([^"]+)"', block)
            if pm:
                pic = pm.group(1)
            if pic.startswith("//"):
                pic = "https:" + pic
            elif pic.startswith("/"):
                pic = self.base_url + pic
            remark = ""
            rm = re.search(r'(?:module-item-text|pic_text|video-serial|public-list-prb)[^>]*>([^<]{1,20})', block)
            if rm:
                remark = rm.group(1).strip()
            items.append({"vod_id": vid, "vod_name": name,
                          "vod_pic": pic, "vod_remarks": remark})
            if len(items) >= limit:
                break
        return items

    def detailContent(self, ids):
        result = {"list": []}
        vid = ""
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ""
        elif isinstance(ids, dict):
            vid = str(ids.get("vod_id") or ids.get("id") or "")
        elif ids is not None:
            vid = str(ids)
        vid = re.sub(r"\D", "", vid)
        if not vid:
            return result
        data = self._api(ac="detail", ids=vid)
        if not data or not data.get("list"):
            return result
        info = data["list"][0]

        names = [x for x in str(info.get("vod_play_from", "")).split("$$$") if x]

        lines = []
        for group in str(info.get("vod_play_url", "")).split("$$$"):
            eps = []
            for token in [t for t in group.split("#") if t.strip()]:
                if "$" in token:
                    ep, url = token.split("$", 1)
                else:
                    ep, url = "正片", token
                eps.append(f"{ep.strip()}${url.strip()}")
            lines.append("#".join(eps))

        vod = {
            "vod_id": str(info.get("vod_id", vid)),
            "vod_name": info.get("vod_name", ""),
            "vod_pic": info.get("vod_pic", ""),
            "type_name": info.get("type_name", ""),
            "vod_year": str(info.get("vod_year", "") or ""),
            "vod_area": info.get("vod_area", ""),
            "vod_lang": info.get("vod_lang", ""),
            "vod_actor": info.get("vod_actor", ""),
            "vod_director": info.get("vod_director", ""),
            "vod_content": re.sub(r"<[^>]+>", "", str(info.get("vod_content", "") or "")),
            "vod_remarks": info.get("vod_remarks", ""),
            "vod_play_from": "$$$".join(names or ["默认线路"]),
            "vod_play_url": "$$$".join(lines),
        }
        result["list"].append(vod)
        return result

    def searchContent(self, key, quick=None, pg="1"):
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        result = {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
        if not key:
            return result
        data = self._api(ac="videolist", wd=str(key), pg=page)
        if data and data.get("list"):
            result["list"] = [self._brief(x) for x in data["list"]]
            result["total"] = int(data.get("total") or 0)
            try:
                result["pagecount"] = int(data.get("pagecount") or 1)
            except Exception:
                result["pagecount"] = 1
        return result

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, id, vipFlags=None):
        url = id or ""
        if url and not re.match(r"^https?://", url):
            url = urljoin(self.base_url + "/", url)
        direct = bool(url) and any(t in url for t in (".m3u8", ".mp4", ".flv", ".mkv"))
        return {
            "parse": 0 if direct else 1,
            "url": url,
            "header": {"User-Agent": self.headers["User-Agent"],
                       "Referer": self.base_url + "/"},
        }

    def isVideoFormat(self, url):
        return any(t in url for t in (".m3u8", ".mp4", ".flv", ".mkv"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass

    def localProxy(self, param):
        return None