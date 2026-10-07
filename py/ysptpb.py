#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""TVBox / 影視倉 Native PySpider 模組 - 央視頻版 (SSL 驗證豁免 & Header 修正版)

文件路徑：./py/ysptpb.py
"""

from datetime import datetime, timedelta
import json
import ssl
import urllib.request

# -------------------------------------------------------------------
# 1. 禁用 Android Python 的 SSL 強制驗證 (解決 CERTIFICATE_VERIFY_FAILED)
# -------------------------------------------------------------------
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

try:
    from base.spider import Spider
except ImportError:

    class Spider:

        def __init__(self):
            pass


CHANNELS = {
    "cctv1": {
        "name": "CCTV1",
        "title": "CCTV-1 綜合",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv2": {
        "name": "CCTV2",
        "title": "CCTV-2 財經",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv3": {
        "name": "CCTV3",
        "title": "CCTV-3 綜藝",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv4": {
        "name": "CCTV4",
        "title": "CCTV-4 中文國際",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv5": {
        "name": "CCTV5",
        "title": "CCTV-5 體育",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv5plus": {
        "name": "CCTV5+",
        "title": "CCTV-5+ 體育賽事",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv6": {
        "name": "CCTV6",
        "title": "CCTV-6 電影",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv7": {
        "name": "CCTV7",
        "title": "CCTV-7 國防軍事",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv8": {
        "name": "CCTV8",
        "title": "CCTV-8 電視劇",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv9": {
        "name": "CCTV9",
        "title": "CCTV-9 紀錄",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv10": {
        "name": "CCTV10",
        "title": "CCTV-10 科教",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv11": {
        "name": "CCTV11",
        "title": "CCTV-11 戲曲",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv12": {
        "name": "CCTV12",
        "title": "CCTV-12 社會與法",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv13": {
        "name": "CCTV13",
        "title": "CCTV-13 新聞",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv14": {
        "name": "CCTV14",
        "title": "CCTV-14 少兒",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv15": {
        "name": "CCTV15",
        "title": "CCTV-15 音樂",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv16": {
        "name": "CCTV16",
        "title": "CCTV-16 奧林匹克",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv17": {
        "name": "CCTV17",
        "title": "CCTV-17 農業農村",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv4k": {
        "name": "CCTV4K",
        "title": "CCTV-4K 超高清",
        "pic": "https://live.cctv.com/favicon.ico",
    },
    "cctv8k": {
        "name": "CCTV8K",
        "title": "CCTV-8K 超高清",
        "pic": "https://live.cctv.com/favicon.ico",
    },
}


class Spider(Spider):

    def getName(self):
        return "央視頻tp"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        return {
            "class": [{"type_id": "1", "type_name": "央視"}],
            "list": [
                {
                    "vod_id": cid,
                    "vod_name": ch["name"],
                    "vod_pic": ch["pic"],
                    "vod_remarks": "直播",
                }
                for cid, ch in CHANNELS.items()
            ],
        }

    def homeVideoContent(self):
        return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        vod_list = []
        if str(tid) == "1":
            vod_list = [
                {
                    "vod_id": cid,
                    "vod_name": ch["name"],
                    "vod_pic": ch["pic"],
                    "vod_remarks": "直播",
                }
                for cid, ch in CHANNELS.items()
            ]
        return {
            "page": 1,
            "pagecount": 1,
            "limit": len(vod_list),
            "total": len(vod_list),
            "list": vod_list,
        }

    def detailContent(self, array):
        if not array:
            return {"list": []}
        tid = array[0]
        if tid not in CHANNELS:
            return {"list": []}

        ch = CHANNELS[tid]
        play_urls = []

        play_urls.append(f"🔴 實時直播${tid}")

        now = datetime.now()
        for i in range(7):
            day_date = now - timedelta(days=i)
            date_str = day_date.strftime("%Y%m%d")
            display_date = day_date.strftime("%m月%d日")
            play_urls.append(
                f"📅 {display_date} 全天回看${tid}__shift__{date_str}"
            )

        vod_detail = {
            "vod_id": tid,
            "vod_name": ch["title"],
            "type_name": "央視",
            "vod_pic": ch["pic"],
            "vod_remarks": "直播",
            "vod_content": f"央視頻原生點播 - {ch['title']}",
            "vod_play_from": "央視頻",
            "vod_play_url": "#".join(play_urls),
        }
        return {"list": [vod_detail]}

    def searchContent(self, key, quick, pg=1):
        vod_list = [
            {
                "vod_id": cid,
                "vod_name": ch["name"],
                "vod_pic": ch["pic"],
                "vod_remarks": "直播",
            }
            for cid, ch in CHANNELS.items()
            if key.lower() in ch["name"].lower()
            or key.lower() in ch["title"].lower()
        ]
        return {"list": vod_list}

    def playerContent(self, flag, id, vipFlags):
        cid = id.split("__shift__")[0]
        shift_date = id.split("__shift__")[1] if "__shift__" in id else ""

        real_url = ""

        # 1. 請求央視 VDN API 獲取真實直播流
        try:
            api_url = f"https://vdn.live.cntv.cn/api/getLiveUrl1.do?channel={cid}&client=channel_cctv"
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                        " AppleWebKit/537.36 (KHTML, like Gecko)"
                        " Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://tv.cctv.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                hls_dict = data.get("hls_url", {})
                real_url = (
                    hls_dict.get("hls1")
                    or hls_dict.get("hls2")
                    or hls_dict.get("hls3")
                    or hls_dict.get("hls4")
                    or ""
                )

            if shift_date and real_url:
                real_url += (
                    f"&timeshift={shift_date}"
                    if "?" in real_url
                    else f"?timeshift={shift_date}"
                )
        except Exception:
            pass

        # 2. 如果 API 解析失敗，自動降級調用本地 v9.0 服務 (8767 端口)
        if not real_url:
            real_url = f"http://127.0.0.1:8767/live/{cid}"

        # 3. 補齊播放器必備標頭 (ExoPlayer 必備)
        return {
            "parse": 0,
            "url": real_url,
            "header": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    " AppleWebKit/537.36 (KHTML, like Gecko)"
                    " Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://tv.cctv.com/",
            },
        }

    def localProxy(self, param):
        pass
