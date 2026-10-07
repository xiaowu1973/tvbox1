#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""TVBox / 影視倉 Native PySpider 模組 - 央視頻版

文件路徑：./py/ysptpb.py
接口類型：type: 3
"""

from datetime import datetime, timedelta
import json
import sys

# 嘗試導入 TVBox 爬蟲基類，若不存在則建立兼容基類
try:
    from base.spider import Spider
except ImportError:

    class Spider:

        def __init__(self):
            pass


# -------------------------------------------------------------------
# 頻道數據庫（僅保留央視頻道）
# -------------------------------------------------------------------
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
        """TVBox 首頁分類與推薦列表"""
        result = {}
        # 僅保留「央視」分類
        result["class"] = [{"type_id": "1", "type_name": "央視"}]

        vod_list = []
        for cid, ch in CHANNELS.items():
            vod_list.append(
                {
                    "vod_id": cid,
                    "vod_name": ch["name"],
                    "vod_pic": ch["pic"],
                    "vod_remarks": "直播",
                }
            )
        result["list"] = vod_list
        return result

    def homeVideoContent(self):
        return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        """分類頁面數據獲取"""
        result = {}
        vod_list = []

        if str(tid) == "1":
            for cid, ch in CHANNELS.items():
                vod_list.append(
                    {
                        "vod_id": cid,
                        "vod_name": ch["name"],
                        "vod_pic": ch["pic"],
                        "vod_remarks": "直播",
                    }
                )

        result["page"] = 1
        result["pagecount"] = 1
        result["limit"] = len(vod_list)
        result["total"] = len(vod_list)
        result["list"] = vod_list
        return result

    def detailContent(self, array):
        """詳情頁：點擊頻道卡片後展開選集（直播 + 近7天回看）"""
        if not array:
            return {"list": []}

        tid = array[0]
        if tid not in CHANNELS:
            return {"list": []}

        ch = CHANNELS[tid]
        play_urls = []

        # 1. 🔴 實時直播流
        live_stream = f"http://live.cctv.com/hls/{tid}/index.m3u8"
        play_urls.append(f"🔴 實時直播${live_stream}")

        # 2. 📅 近 7 天歷史回看
        now = datetime.now()
        for i in range(7):
            day_date = now - timedelta(days=i)
            date_str = day_date.strftime("%Y%m%d")
            display_date = day_date.strftime("%m月%d日")
            timeshift_stream = f"http://live.cctv.com/hls/{tid}/index.m3u8?timeshift={date_str}"
            play_urls.append(f"📅 {display_date} 全天回看${timeshift_stream}")

        vod_detail = {
            "vod_id": tid,
            "vod_name": ch["title"],
            "type_name": "央視",
            "vod_pic": ch["pic"],
            "vod_remarks": "直播",
            "vod_content": f"央視頻原生點播 - {ch['title']}，支持 7 天時移回看。",
            "vod_play_from": "央視頻",
            "vod_play_url": "#".join(play_urls),
        }

        return {"list": [vod_detail]}

    def searchContent(self, key, quick, pg=1):
        """搜尋功能"""
        vod_list = []
        for cid, ch in CHANNELS.items():
            if (
                key.lower() in ch["name"].lower()
                or key.lower() in ch["title"].lower()
            ):
                vod_list.append(
                    {
                        "vod_id": cid,
                        "vod_name": ch["name"],
                        "vod_pic": ch["pic"],
                        "vod_remarks": "直播",
                    }
                )
        return {"list": vod_list}

    def playerContent(self, flag, id, vipFlags):
        """播放器解析，直接回傳直鏈"""
        return {
            "parse": 0,
            "url": id,
            "header": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.cctv.com/",
            },
        }

    def localProxy(self, param):
        pass
