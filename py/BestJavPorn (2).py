# coding=utf-8
# TVBox / FongMi T3 (type=3) Spider  —  bestjavporn.me (JAV / Censored)
# 逆向要點（2026-10 新域 .me 重寫）：
#   詳情頁 <div class="box-server" data-server-urls="[密文1,密文2,密文3]"> + 按鈕 LV/WS/XS
#   第2層：datalink 密文 → RC4-like XOR(固定KEY=KmzWa8awaallakclnu，先反轉再 urlsafe b64) → /xx/{token}
#   第3層：GET /xx/{token}(Referer+UA) → JWPlayer 頁含 pox + dp
#   第4層：CryptoJS-AES(OpenSSL/EvpKDF-MD5)，passphrase = pox.split('+')[1][1:]
#          dp=base64({ct,iv,s}) → 解出 api.videplay.us/ved/v-master.m3u8/{token} 直鏈(parse:0)
import sys, re, base64, json, hashlib
sys.path.append('..')
try:
    from base.spider import Spider
except Exception:
    class Spider(object):  # 本地冒煙測試兜底（正式環境由 T3 提供）
        def init(self, extend=""): pass

try:
    from Crypto.Cipher import AES  # pycryptodome
except Exception:
    AES = None


class Spider(Spider):

    # ---------------- 站點常量（換站只改這裡） ----------------
    siteName = "JAV"
    HOST = "https://bestjavporn.me"
    UA = "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    # datalink 固定解密金鑰（JS _0x512c 動態產出，已固化）
    DATALINK_KEY = "KmzWa8awaallakclnu"

    def getName(self):
        return self.siteName

    def init(self, extend=""):
        self.headers = {
            "User-Agent": self.UA,
            "Referer": self.HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        return

    def isVideoFormat(self, url):
        if not url:
            return False
        u = url.lower()
        return (".m3u8" in u) or (".mp4" in u) or ("master.m3u8" in u)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return

    # ---------------- 網路封裝（法則4：fetch 失敗回 None 須判空） ----------------
    def _get(self, url, headers=None, allow_redirects=True):
        h = dict(self.headers)
        if headers:
            h.update(headers)
        try:
            rsp = self.fetch(url, headers=h, allow_redirects=allow_redirects)
            if rsp is None:
                return None
            code = getattr(rsp, "status_code", getattr(rsp, "code", 200))
            if code and int(code) >= 400:
                return None
            return rsp.text
        except Exception:
            # 本地冒煙測試 / 無 self.fetch 時走 requests
            try:
                import requests
                r = requests.get(url, headers=h, timeout=20, allow_redirects=allow_redirects)
                if r.status_code >= 400:
                    return None
                return r.text
            except Exception:
                return None

    def _get_final_html(self, url):
        """取跳轉後最終頁 HTML（用於 /xx/ → HORNYJAV 播放頁）。"""
        try:
            import requests
            r = requests.get(url, headers={"User-Agent": self.UA, "Referer": self.HOST + "/"},
                             timeout=20, allow_redirects=True)
            if r.status_code >= 400:
                return None, url
            return r.text, r.url
        except Exception:
            return self._get(url), url

    # ---------------- 列表卡片解析 ----------------
    def _parse_cards(self, html):
        vods = []
        if not html:
            return vods
        blocks = re.findall(r'<article[^>]*class="[^"]*loop-video[^"]*"[^>]*>(.*?)</article>',
                            html, re.S)
        if not blocks:
            # 兜底：直接抓詳情連結
            blocks = re.findall(r'(<a[^>]+href="https?://[^"]+"[^>]*title="[^"]*"[\s\S]{0,400}?)(?=<a[^>]+title=|</article>|$)', html)
        seen = set()
        for b in blocks:
            m = re.search(r'href="(https?://[^"]*bestjavporn\.me/[^"/]+)/?"\s+title="([^"]*)"', b)
            if not m:
                m = re.search(r'href="(https?://[^"]+)"\s+title="([^"]+)"', b)
            if not m:
                continue
            link, title = m.group(1), m.group(2)
            slug = link.rstrip("/").split("/")[-1]
            if not slug or slug in seen:
                continue
            # 過濾非影片連結（分類/分頁等）
            if slug in ("category", "page", "tag", "censored") or slug.isdigit():
                continue
            seen.add(slug)
            pm = re.search(r'data-src="([^"]+)"', b) or re.search(r'\ssrc="(https?://[^"]+)"', b)
            pic = pm.group(1) if pm else ""
            dm = re.search(r'class="duration"[^>]*>([^<]+)<', b)
            remark = dm.group(1).strip() if dm else ""
            vods.append({
                "vod_id": slug,
                "vod_name": self._clean(title),
                "vod_pic": pic,
                "vod_remarks": remark,
            })
        return vods

    def _clean(self, s):
        if not s:
            return ""
        s = re.sub(r"<[^>]+>", "", s)
        return s.replace("&amp;", "&").replace("&#039;", "'").replace("&quot;", '"').strip()

    def _pagecount(self, html, pg):
        try:
            nums = [int(x) for x in re.findall(r'/page/(\d+)/', html or "")]
            if nums:
                return max(max(nums), int(pg))
        except Exception:
            pass
        return 9999  # 未知總頁：保持可翻頁

    # ---------------- homeContent：靜態分類，零網路（法則16/17） ----------------
    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_id": "latest", "type_name": "最新"},
            {"type_id": "censored", "type_name": "有碼(Censored)"},
        ]
        result["class"] = classes
        result["filters"] = {}
        return result

    # homeVideoContent：首頁推薦（每頁 28 卡）
    def homeVideoContent(self):
        html = self._get(self.HOST + "/")
        return {"list": self._parse_cards(html)}

    # ---------------- categoryContent ----------------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        if tid == "censored":
            base = self.HOST + "/category/censored/"
            url = base if pg == 1 else "%spage/%d/" % (base, pg)
        else:  # latest：首頁(第1頁) → 之後接 censored 分頁延續最新流
            if pg == 1:
                url = self.HOST + "/"
            else:
                url = "%s/category/censored/page/%d/" % (self.HOST, pg)
        html = self._get(url)
        vods = self._parse_cards(html)
        result = {
            "list": vods,
            "page": pg,
            "pagecount": self._pagecount(html, pg) if vods else max(pg, 1),
            "limit": len(vods) if vods else 20,
            "total": 999999,
        }
        return result

    # ---------------- searchContent ----------------
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        import urllib.parse as up
        q = up.quote(key)
        if pg == 1:
            url = "%s/?s=%s" % (self.HOST, q)
        else:
            url = "%s/?s=%s&paged=%d" % (self.HOST, q, pg)
        html = self._get(url)
        vods = self._parse_cards(html)
        return {"list": vods, "page": pg, "pagecount": (pg + 1) if vods else pg,
                "limit": len(vods), "total": 999999}

    # ---------------- detailContent（法則35） ----------------
    def detailContent(self, ids):
        ids = self._norm_ids(ids)
        if not ids:
            return {"list": []}
        vid = ids[0]
        url = "%s/%s" % (self.HOST, vid)
        html = self._get(url)
        if not html:
            return self._skeleton(vid)

        title = self._first(html, [
            r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
            r'<h1[^>]*>([^<]+)</h1>',
            r'<title>([^<]+)</title>',
        ]) or vid
        pic = self._first(html, [
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r'poster="([^"]+)"',
            r'data-src="([^"]+)"',
        ]) or ""
        desc = self._first(html, [
            r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
        ]) or ""
        remark = self._first(html, [r'class="duration"[^>]*>([^<]+)<']) or ""

        # 解出多線路播放入口（LV/WS/XS → /xx/{token}）
        servers = self._extract_servers(html)
        if servers:
            froms = "$$$".join([s[0] for s in servers])
            urls = "$$$".join(["正片$" + s[1] for s in servers])
            vod_from, vod_url = froms, urls
        else:
            # 兜底：直接用番號頁自身，playerContent 再嘗試
            vod_from, vod_url = self.siteName, "正片$" + url

        vod = {
            "vod_id": vid,
            "vod_name": self._clean(title),
            "vod_pic": pic,
            "vod_remarks": self._clean(remark),
            "vod_content": self._clean(desc),
            "vod_play_from": vod_from,
            "vod_play_url": vod_url,
        }
        return {"list": [vod]}

    def _dec_datalink(self, s):
        """datalink 密文 → /xx/{token} 明文（先反轉 → urlsafe b64 → XOR 固定KEY）。"""
        try:
            t = s[::-1].replace("-", "+").replace("_", "/")
            t += "=" * ((4 - len(t) % 4) % 4)
            raw = base64.b64decode(t)
            key = self.DATALINK_KEY
            out = bytes(raw[i] ^ ord(key[i % len(key)]) for i in range(len(raw)))
            return out.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _extract_servers(self, html):
        """回傳 [(label, playUrl), ...]；label 取自按鈕 value，順序對齊 data-server-urls。"""
        import html as _h
        servers = []
        m = re.search(r'data-server-urls="([^"]+)"', html)
        if not m:
            return servers
        try:
            arr = json.loads(_h.unescape(m.group(1)))
        except Exception:
            arr = re.findall(r'&quot;([^&]+)&quot;', m.group(1)) or re.findall(r'"([^"]+)"', m.group(1))
        # 按鈕標籤（LV/WS/XS…），順序對齊密文陣列
        labels = re.findall(r'<input[^>]+type="button"[^>]+value="([^"]+)"', html)
        seen = set()
        for i, cipher in enumerate(arr):
            play = self._dec_datalink(cipher)
            if not play or not play.startswith("http"):
                continue
            label = labels[i] if i < len(labels) else ("线路%d" % (i + 1))
            if label in seen:
                label = "%s%d" % (label, i + 1)
            seen.add(label)
            servers.append((label, play))
        return servers

    # ---------------- playerContent（parse:0 直鏈，法則5/7/36） ----------------
    def playerContent(self, flag, id, vipFlags):
        header = {"User-Agent": self.UA, "Referer": self.HOST + "/"}
        m3u8 = None
        # id = /xx/{token}；GET 取 JWPlayer 頁 → 解 pox/dp → videplay m3u8
        if id and id.startswith("http"):
            play_html = self._get(id, headers={"Referer": self.HOST + "/"})
            if play_html:
                m3u8 = self._decrypt_m3u8(play_html)
                if not m3u8:
                    # 兜底：若拿到的是番號頁，先解 /xx/ 再跳一次
                    servers = self._extract_servers(play_html)
                    if servers:
                        ph2 = self._get(servers[0][1], headers={"Referer": self.HOST + "/"})
                        if ph2:
                            m3u8 = self._decrypt_m3u8(ph2)
        if not m3u8:
            m3u8 = id  # 最終兜底：交由播放器嘗試
        return {"parse": 0, "playUrl": "", "url": m3u8, "header": header}

    def _decrypt_m3u8(self, html):
        # 取 pox / dp（CryptoJS-AES）
        mp = re.search(r"pox\s*=\s*'([^']+)'", html) or re.search(r'pox\s*=\s*"([^"]+)"', html)
        md = re.search(r"dp\s*=\s*'([^']+)'", html) or re.search(r'dp\s*=\s*"([^"]+)"', html)
        if mp and md and AES is not None:
            try:
                url = self._ply(mp.group(1), md.group(1))
                if url and isinstance(url, str) and "http" in url:
                    return url
            except Exception:
                pass
        # 明文 fallback：直接抓 videplay master 連結
        direct = re.search(r'https?://[^"\'\s\\]*videplay\.us/[^"\'\s\\]*master\.m3u8/[A-Za-z0-9+/=%]+', html)
        if direct:
            return direct.group(0)
        return None

    # CryptoJS-AES(OpenSSL/EvpKDF-MD5) Python 復刻（pyverify.py 已驗證）
    def _evp_kdf(self, password, salt, key_len=32, iv_len=16):
        d = b""; prev = b""
        while len(d) < key_len + iv_len:
            prev = hashlib.md5(prev + password + salt).digest()
            d += prev
        return d[:key_len], d[key_len:key_len + iv_len]

    def _ply(self, pox, dp_b64):
        key_pass = pox.split("+")[1][1:]                       # pr()
        obj = json.loads(base64.b64decode(dp_b64).decode("utf-8"))  # dct()=atob
        ct = base64.b64decode(obj["ct"])
        salt = bytes.fromhex(obj["s"])
        key, iv = self._evp_kdf(key_pass.encode("utf-8"), salt)  # 忽略 obj['iv']
        pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
        pt = pt[:-pt[-1]]
        return json.loads(pt.decode("utf-8"))

    # ---------------- localProxy：m3u8 直通/絕對化（法則26，僅文本不緩衝分片） ----------------
    def localProxy(self, param):
        try:
            import requests, urllib.parse as up
            url = param.get("url") if isinstance(param, dict) else None
            if not url:
                return [404, "text/plain", b""]
            url = up.unquote(url)
            h = {"User-Agent": self.UA, "Referer": self.HOST + "/"}
            r = requests.get(url, headers=h, timeout=20)
            text = r.text
            base = url.rsplit("/", 1)[0] + "/"
            out = []
            for ln in text.splitlines():
                s = ln.strip()
                if s and not s.startswith("#") and not s.startswith("http"):
                    s = up.urljoin(base, s)  # 相對片段絕對化（後綴原樣透傳，法則33）
                out.append(s)
            body = ("\n".join(out)).encode("utf-8")
            return [200, "application/vnd.apple.mpegurl", body]
        except Exception:
            return [404, "text/plain", b""]

    # ---------------- 通用工具 ----------------
    def _first(self, html, patterns):
        for p in patterns:
            m = re.search(p, html, re.S)
            if m:
                return m.group(1).strip()
        return None

    def _norm_ids(self, ids):
        if ids is None:
            return []
        if isinstance(ids, str):
            ids = [ids]
        out = []
        for x in ids:
            if x is None:
                continue
            s = str(x).strip()
            if not s:
                continue
            if s.startswith("http"):
                s = s.rstrip("/").split("/")[-1]
            out.append(s)
        return out

    def _skeleton(self, vid):
        vod = {
            "vod_id": vid,
            "vod_name": vid,
            "vod_pic": "",
            "vod_remarks": "",
            "vod_content": "詳情載入失敗，可直接嘗試播放",
            "vod_play_from": self.siteName,
            "vod_play_url": "正片$" + ("%s/%s" % (self.HOST, vid)),
        }
        return {"list": [vod]}

    # T3 其它可選接口
    def liveContent(self, url):
        return {}

    def action(self, action):
        return ""
