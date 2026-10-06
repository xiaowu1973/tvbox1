# coding=utf-8
import sys
import re
import json
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    session = requests.Session()

    def __init__(self):
        self.name = "MMRGB"
        self.host = "https://mmrgb.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://mmrgb.com/",
        }
        self.forums = [
            {"type_id": "2", "type_name": "XiuRen 秀人网"},
            {"type_id": "5", "type_name": "MyGirl 美媛馆"},
            {"type_id": "7", "type_name": "BoLoLi 波萝社"},
            {"type_id": "4", "type_name": "MiStar 魅妍社"},
            {"type_id": "3", "type_name": "MFStar 模范学院"},
            {"type_id": "9", "type_name": "UXing 优星馆"},
            {"type_id": "6", "type_name": "Imiss 爱蜜社"},
            {"type_id": "11", "type_name": "FeiLin 嗲囡囡"},
            {"type_id": "13", "type_name": "Taste 顽味生活"},
            {"type_id": "10", "type_name": "MiiTao 蜜桃社"},
            {"type_id": "8", "type_name": "YouWu 尤物馆"},
            {"type_id": "12", "type_name": "WingS 影私荟"},
            {"type_id": "14", "type_name": "LeYuan 星乐园"},
            {"type_id": "15", "type_name": "HuaYan 花の颜"},
            {"type_id": "17", "type_name": "MintYe 薄荷叶"},
            {"type_id": "16", "type_name": "DKGirl 御女郎"},
            {"type_id": "19", "type_name": "Candy 糖果画报"},
            {"type_id": "18", "type_name": "YouMi 尤蜜荟"},
            {"type_id": "20", "type_name": "MTMeng 模特联盟"},
            {"type_id": "21", "type_name": "MiCat 猫萌榜"},
            {"type_id": "22", "type_name": "HuaYang 花漾show"},
            {"type_id": "23", "type_name": "XingYan 星颜社"},
            {"type_id": "24", "type_name": "XiaoYu 语画界"},
        ]

    def getName(self):
        return self.name

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, params):
        return None

    def _fetch(self, path):
        try:
            url = f"{self.host}/{path}" if not path.startswith("http") else path
            r = self.session.get(url, headers=self.headers, timeout=15, verify=False)
            r.encoding = "utf-8"
            return r.text
        except:
            return ""

    def homeContent(self, filter):
        return {
            "class": self.forums,
            "filters": {},
        }

    def homeVideoContent(self):
        videos = []
        try:
            html = self._fetch("portal.php?order=favnew&page=1")
            videos = self._parse_portal(html)
        except:
            pass
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        videos = []
        try:
            page = int(pg) if pg else 1
            html = self._fetch(f"forum-{tid}-{page}.html")
            videos = self._parse_forum(html)
            return {
                "page": page,
                "pagecount": 999,
                "limit": len(videos),
                "total": 99999,
                "list": videos,
            }
        except:
            pass
        return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}

    def detailContent(self, ids):
        try:
            tid = ids[0] if isinstance(ids, list) else str(ids)
            # 帖子可能有多页，先尝试第1页
            html = self._fetch(f"thread-{tid}-1-1.html")
            title = self._extract_title(html)
            images = self._extract_images(html)

            # 检查是否有更多页
            pages = self._find_thread_pages(html)
            for p in range(2, pages + 1):
                html2 = self._fetch(f"thread-{tid}-{p}-1.html")
                images.extend(self._extract_images(html2))

            pics_url = "&&".join(images)
            cover = images[0] if images else ""

            vod = {
                "vod_id": tid,
                "vod_name": title,
                "vod_pic": cover,
                "vod_remarks": f"{len(images)}图",
                "vod_play_from": "MMRGB",
                "vod_play_url": f"图集$pics://{pics_url}",
            }
            return {"list": [vod]}
        except:
            pass
        return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        # 搜索有 Cloudflare 挑战，跳过
        return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        try:
            # 处理 "图集$pics://..." 格式
            url = id
            if "$" in id:
                url = id.split("$")[-1]
            if url.startswith("pics://"):
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": url,
                    "header": self.headers,
                }
            return {"parse": 0, "url": url, "header": self.headers}
        except:
            return {"parse": 0, "url": "", "header": ""}

    # ---- 解析方法 ----

    def _parse_portal(self, html):
        """解析 portal.php 推荐页"""
        videos = []
        # 匹配卡片: ui8-image + title + thread link
        pattern = r'ui8-image="(https://attachment\.mmrgb\.com/forum/threadcover/[^"]+)"[^>]*>.*?<br />\s*(.*?)\s*</p>.*?thread-(\d+)-'
        for m in re.finditer(pattern, html, re.DOTALL):
            pic, title, tid = m.group(1), m.group(2).strip(), m.group(3)
            title = re.sub(r'<[^>]+>', '', title).strip()
            videos.append({
                "vod_id": tid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
            })
        return videos

    def _parse_forum(self, html):
        """解析 forum 分类列表页"""
        videos = []
        pattern = r'ui8-image="(https://attachment\.mmrgb\.com/forum/threadcover/[^"]+)"[^>]*>.*?<br />\s*(.*?)\s*</p>.*?thread-(\d+)-'
        for m in re.finditer(pattern, html, re.DOTALL):
            pic, title, tid = m.group(1), m.group(2).strip(), m.group(3)
            title = re.sub(r'<[^>]+>', '', title).strip()
            views = ""
            vm = re.search(r'fa-eye[^>]*>\s*</i>\s*(\d+)', m.group(0))
            if vm:
                views = f"👁{vm.group(1)}"
            videos.append({
                "vod_id": tid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": views,
            })
        return videos

    def _extract_title(self, html):
        """提取帖子标题"""
        m = re.search(r'<title>(.*?)</title>', html)
        if m:
            t = m.group(1).strip()
            return t.split(" - ")[0].strip() if " - " in t else t
        return "未知"

    def _extract_images(self, html):
        """提取帖子中的图片URL"""
        images = []
        for m in re.finditer(r'ui8-image="(https://[^"]+\.(?:jpg|jpeg|png|webp|gif))"', html):
            url = m.group(1)
            if "threadcover" not in url and url not in images:
                images.append(url)
        return images

    def _find_thread_pages(self, html):
        """查找帖子总页数"""
        pages = 1
        for m in re.finditer(r'thread-\d+-(\d+)-\d+\.html', html):
            p = int(m.group(1))
            if p > pages:
                pages = p
        return pages
