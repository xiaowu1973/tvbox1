import sys
sys.path.append('..')
from base.spider import Spider
import base64
import json
import re
import time
import urllib.parse


class Spider(Spider):
    HOST = "https://www.bestjavporn.com"
    SALT = "_0x58fe15"
    PSALT = "_0x59a0e4"
    UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")

    def init(self, extend=""):
        self._ok = None
        try:
            from okhttp3 import OkHttpClient
            from java.util.concurrent import TimeUnit
            self._ok = (OkHttpClient.Builder()
                        .connectTimeout(15, TimeUnit.SECONDS)
                        .readTimeout(20, TimeUnit.SECONDS)
                        .followRedirects(True).build())
        except Exception:
            self._ok = None
        self._cf = None
        try:
            from curl_cffi import requests as _cf
            self._cf = _cf.Session(impersonate="chrome124")
        except Exception:
            self._cf = None
        try:
            import requests as _rq
            self._rq = _rq
        except Exception:
            self._rq = None
        self.classes = [
            {"type_id": "/v38/category/censored/", "type_name": "有码"},
            {"type_id": "/v11/category/uncensored/", "type_name": "无码"},
            {"type_id": "/v23/category/decensored/", "type_name": "无码破解"},
            {"type_id": "/v21/category/amateur/", "type_name": "素人"},
            {"type_id": "/v9/category/censored/english-subtitle/", "type_name": "英文字幕"},
            {"type_id": "/v14/category/chinese-subtitle/", "type_name": "中文字幕"},
        ]
        return None

    def getName(self):
        return "BestJavPorn"

    def isVideoFormat(self, url):
        return bool(url) and (".m3u8" in url or ".mp4" in url)

    def manualVideoCheck(self):
        return False

    # ---------------- HTTP: okhttp bridge -> requests ----------------
    def _hdr(self, referer=None):
        h = {"User-Agent": self.UA}
        if referer:
            h["Referer"] = referer
            h["Origin"] = self.HOST
        return h

    def _get(self, url, referer=None):
        h = self._hdr(referer)
        if self._ok is not None:
            try:
                from okhttp3 import Request
                b = Request.Builder().url(url)
                for k, v in h.items():
                    b.header(k, v)
                resp = self._ok.newCall(b.build()).execute()
                code = resp.code()
                data = bytes(resp.body().bytes())
                resp.close()
                if code == 200:
                    return data
                raise RuntimeError("HTTP %d" % code)
            except Exception as e:
                self.log("okhttp get fail: %s" % e)
        if self._cf is not None:
            try:
                r = self._cf.get(url, headers=h, timeout=20)
                if r.status_code == 200:
                    return r.content
                self.log("cf get HTTP %d" % r.status_code)
            except Exception as e:
                self.log("cf get fail: %s" % e)
        if self._rq:
            r = self._rq.get(url, headers=h, timeout=20)
            r.raise_for_status()
            return r.content
        raise RuntimeError("no http backend")

    def _post(self, url, form, referer=None):
        h = self._hdr(referer)
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        h["X-Requested-With"] = "XMLHttpRequest"
        body = urllib.parse.urlencode(form)
        if self._ok is not None:
            try:
                from okhttp3 import Request, RequestBody, MediaType
                from java import String as JStr
                mt = MediaType.parse("application/x-www-form-urlencoded")
                rb = RequestBody.create(JStr(body), mt)
                b = Request.Builder().url(url)
                for k, v in h.items():
                    b.header(k, v)
                b = b.post(rb)
                resp = self._ok.newCall(b.build()).execute()
                code = resp.code()
                data = bytes(resp.body().bytes())
                resp.close()
                if code == 200:
                    return data
                raise RuntimeError("HTTP %d" % code)
            except Exception as e:
                self.log("okhttp post fail: %s" % e)
        if self._cf is not None:
            try:
                r = self._cf.post(url, data=body, headers=h, timeout=20)
                if r.status_code == 200:
                    return r.content
                self.log("cf post HTTP %d" % r.status_code)
            except Exception as e:
                self.log("cf post fail: %s" % e)
        if self._rq:
            r = self._rq.post(url, data=body, headers=h, timeout=20)
            r.raise_for_status()
            return r.content
        raise RuntimeError("no http backend")

    # ---------------- crypto ----------------
    @staticmethod
    def _rc4(key, data):
        if isinstance(key, str):
            key = key.encode()
        S = list(range(256))
        j = 0
        for i in range(256):
            j = (j + S[i] + key[i % len(key)]) & 0xFF
            S[i], S[j] = S[j], S[i]
        out = bytearray()
        i = j = 0
        for b in data:
            i = (i + 1) & 0xFF
            j = (j + S[i]) & 0xFF
            S[i], S[j] = S[j], S[i]
            out.append(b ^ S[(S[i] + S[j]) & 0xFF])
        return bytes(out)

    @staticmethod
    def _b64d(s):
        if isinstance(s, bytes):
            s = s.decode("latin-1")
        s = s.strip()
        pad = -len(s) % 4
        try:
            return base64.b64decode(s + "=" * pad)
        except Exception:
            return base64.urlsafe_b64decode(s + "=" * pad)

    def _site_key(self, vid):
        return base64.b64encode(("%s%s" % (vid, self.SALT)).encode()).decode()[::-1]

    def _player_key(self, phash):
        b64h = base64.b64encode(phash.encode()).decode().rstrip("=")
        return base64.b64encode(("%s%s" % (b64h, self.PSALT)).encode()).decode()[::-1]

    def _site_dec(self, key, blob):
        return self._b64d(self._rc4(key, self._b64d(blob))).decode()

    # ---------------- parse helpers ----------------
    def _card_pic(self, block):
        for img in re.finditer(r'<img[^>]*>', block):
            tag = img.group(0)
            for attr in ("data-lazy-src", "data-original", "data-src", "src", "data-wpsrc"):
                m = re.search(r'\b%s="([^"]+)"' % attr, tag)
                if m and m.group(1).startswith("http") and "svg" not in m.group(1)[:30]:
                    return m.group(1)
        return ""

    def _cards(self, html):
        out = []
        seen = set()
        for block in re.findall(r'<article[^>]*>.*?</article>', html, re.S):
            a = re.search(r'<a href="(https?://[^"]+/video/[^"]+)"', block)
            if not a:
                continue
            url = a.group(1)
            if url in seen:
                continue
            t = re.search(r'<a[^>]+title="([^"]*)"', block) or re.search(r'class="title">([^<]+)<', block)
            title = t.group(1).strip() if t else url.rstrip("/").split("/")[-1].replace("-", " ")
            seen.add(url)
            out.append({"vod_id": url, "vod_name": title, "vod_pic": self._card_pic(block)})
        if not out:
            for m in re.finditer(r'<a href="(https?://[^"]+/video/[^"]+)"[^>]*title="([^"]*)"', html):
                if m.group(1) not in seen and m.group(2).strip():
                    seen.add(m.group(1))
                    out.append({"vod_id": m.group(1), "vod_name": m.group(2).strip(), "vod_pic": ""})
        return out

    # ---------------- API ----------------
    def homeContent(self, filter):
        try:
            html = self._get(self.HOST + "/?sort=latest").decode("utf-8", "replace")
            return {"class": self.classes, "list": self._cards(html)}
        except Exception as e:
            self.log("homeContent: %s" % e)
            return {"class": self.classes, "list": []}

    def homeVideoContent(self):
        try:
            html = self._get(self.HOST + "/?sort=latest").decode("utf-8", "replace")
            return {"list": self._cards(html)}
        except Exception as e:
            self.log("homeVideoContent: %s" % e)
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            url = self.HOST + tid if tid.startswith("/") else tid
            if page > 1:
                url = url.rstrip("/") + "/page/%d/" % page
            html = self._get(url).decode("utf-8", "replace")
            return {"list": self._cards(html), "page": page, "pagecount": 999,
                    "limit": 24, "total": 999 * 24}
        except Exception as e:
            self.log("categoryContent: %s" % e)
            return {"list": [], "page": int(pg or 1), "pagecount": 0, "limit": 0, "total": 0}

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            url = self.HOST + "/en/search/%s/" % urllib.parse.quote(key)
            if page > 1:
                url = url.rstrip("/") + "/page/%d/" % page
            html = self._get(url).decode("utf-8", "replace")
            return {"list": self._cards(html), "page": page}
        except Exception as e:
            self.log("searchContent: %s" % e)
            return {"list": [], "page": int(pg or 1)}

    def _servers(self, vurl):
        html = self._get(vurl, referer=self.HOST + "/").decode("utf-8", "replace")
        vid = re.search(r'video-id="(\d+)"', html)
        mpu = re.search(r'data-mpu="([^"]+)"', html)
        ver = re.search(r'video_ver="(\d+)"', html)
        if not (vid and mpu):
            raise RuntimeError("no data-mpu")
        key = self._site_key(vid.group(1))
        sources = self._site_dec(key, mpu.group(1))
        resp = self._post(self.HOST + "/api/play/",
                          {"sources": sources, "ver": ver.group(1) if ver else "2"},
                          referer=vurl)
        obj = json.loads(resp)
        if not obj.get("status"):
            raise RuntimeError("api status false")
        urls = []
        for field in ("data", "reserve"):
            blob = obj.get(field)
            if not blob:
                continue
            try:
                dec = self._site_dec(key, blob)
                if dec.startswith("["):
                    for item in json.loads(dec):
                        sub = item.get("data") if isinstance(item, dict) else item
                        if sub:
                            try:
                                urls.append(self._site_dec(key, sub))
                            except Exception:
                                pass
                else:
                    urls.append(dec)
            except Exception:
                pass
        return urls

    def detailContent(self, ids):
        try:
            vurl = ids[0]
            html = self._get(vurl, referer=self.HOST + "/").decode("utf-8", "replace")
            title = re.search(r'<h1[^>]*class="entry-title"[^>]*>([^<]+)</h1>', html)
            title = title.group(1).strip() if title else vurl.rstrip("/").split("/")[-1]
            pic = re.search(r'og:image[^>]+content="([^"]+)"', html) or re.search(r'property="og:image" content="([^"]+)"', html)
            desc = re.search(r'<div class="video-description[^"]*">.*?<p>(.*?)</p>', html, re.S)
            date = re.search(r'class="video-meta[^"]*">.*?(\d{4}-\d{2}-\d{2})', html, re.S)
            vod = {
                "vod_id": vurl,
                "vod_name": title,
                "vod_pic": pic.group(1) if pic else "",
                "vod_remarks": (date.group(1) if date else "BJP"),
                "vod_content": re.sub(r"<[^>]+>", "", desc.group(1)).strip() if desc else "",
            }
            try:
                servers = self._servers(vurl)
            except Exception:
                servers = []
            if not servers:
                servers = ["__direct__"]
            names = []
            play = []
            for i in range(len(servers)):
                names.append("线路%d" % (i + 1))
                play.append("播放$%s@@%d" % (vurl, i))
            vod["vod_play_from"] = "$$$".join(names)
            vod["vod_play_url"] = "$$$".join(play)
            return {"list": [vod]}
        except Exception as e:
            self.log("detailContent: %s" % e)
            return {"list": []}

    def _probe(self, url, backend):
        try:
            if backend == "ok":
                from okhttp3 import Request
                b = Request.Builder().url(url).header("User-Agent", self.UA)
                b.header("Referer", self.HOST + "/")
                b.header("Range", "bytes=0-256")
                resp = self._ok.newCall(b.build()).execute()
                code = resp.code()
                ctype = resp.header("Content-Type") or ""
                resp.close()
                return code in (200, 206) and "text/html" not in ctype, ctype
            if backend == "cf":
                r = self._cf.get(url, timeout=8, headers={
                    "User-Agent": self.UA, "Referer": self.HOST + "/",
                    "Range": "bytes=0-256"})
                return r.status_code in (200, 206) and "text/html" not in (r.headers.get("content-type") or ""), r.headers.get("content-type") or ""
        except Exception:
            pass
        return False, ""

    def playerContent(self, flag, id, vipFlags):
        try:
            vurl, idx = id.rsplit("@@", 1)
            idx = int(idx)
            servers = []
            if "__direct__" not in id:
                servers = self._servers(vurl)
            if idx >= len(servers):
                raise RuntimeError("server idx out of range")
            cands = []
            for i, s in enumerate(servers):
                if i == idx:
                    cands.insert(0, s)
                else:
                    cands.append(s)
            backend = "ok" if self._ok is not None else ("cf" if self._cf is not None else None)
            last_err = None
            for purl in cands:
                try:
                    if purl.startswith("//"):
                        purl = "https:" + purl
                    ph = self._get(purl, referer=self.HOST + "/").decode("utf-8", "replace")
                    cfg = re.search(r'data-config="([^"]+)"', ph)
                    if not cfg:
                        raise RuntimeError("no data-config")
                    phash = re.search(r"/p/([A-Za-z0-9_-]+)", purl).group(1)
                    pkey = self._player_key(phash)
                    mid = json.loads(self._b64d(self._rc4(pkey, self._b64d(cfg.group(1)))))
                    srcs = json.loads(self._b64d(mid["src"]))
                    urls = []
                    for s in srcs:
                        u = s.get("file", "")
                        if u.startswith("//"):
                            u = "https:" + u
                        if u and "master.php" not in u:
                            urls.append(u)
                    if not urls:
                        raise RuntimeError("no direct file")
                    for u in urls:
                        ok, ctype = self._probe(u, backend) if backend else (True, "")
                        if ok:
                            out = {"parse": 0, "url": u,
                                   "header": {"User-Agent": self.UA, "Referer": self.HOST + "/"}}
                            if "mpegurl" in ctype.lower():
                                out["format"] = "application/x-mpegURL"
                            return out
                    raise RuntimeError("all files dead")
                except Exception as e:
                    last_err = e
                    continue
            raise RuntimeError(str(last_err))
        except Exception as e:
            self.log("playerContent: %s" % e)
            return {"parse": 1, "url": id.split("@@")[0], "header": {}}

    def localProxy(self, param):
        return None

    def destroy(self):
        return None
