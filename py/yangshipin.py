#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
央视频直播 - 单源多模式版 (JCE 25312 / bkliveinfo)，TVBox / FongMi / VodPlus 爬虫版

用法一：当直播源（live 里填）
{
"api": "./yangshipin.py",
"ext": {},
"name": "央视频"
}

用法二：当点播站（site 里填）
{
"key": "yangshipin_vod", "name": "央视频",
"type": 3,
"api": "./yangshipin.py", "ext": {}
}

ext 可选：
  epg_xml         直播源 M3U 的节目单地址，默认 https://epg.112114.xyz/pp.xml，留空则不写
  epg_ids         覆盖 tvg-id 映射，如 {"CCTV-1 综合": "CCTV1"}
  logo_mode       direct(默认) 台标走 CDN 直连；proxy 则全部走本地代理
  direct          true = 全部请求走 urllib，不借容器的 self.fetch()，排错时用
  wait            打开频道时等待首帧就绪的秒数，默认 12
  cast_wait       打开投屏线路时等待握手的秒数，默认 20（比源1慢，要给足时间）
  holdback        播放列表尾部保留几片不播，默认 1（防刚抓到的切片没落地）
  ts_cache_mb     切片缓存上限(MB)，默认 0=关闭
  cast_entries    true 时直播源 M3U 也导出投屏条目（默认 false，只出源1）
  live_mode       proxy(默认) 走代理滚动缓冲；redirect 直接 302 到官方 m3u8，
                  省掉握手等待（投屏源必须带签名头，会自动退回 proxy）
  cast_timeout / cast_insecure / cast_cache_ttl / cast_interval / cast_jitter
  cast_session_ttl / cast_heartbeat / cast_links / cast_persist / cast_device_json

排错：浏览器打开 代理地址?type=diag
      加 &slug=cctv1 会当场拉一次流（&mode=redirect 则测直连取址）

多模式兼容说明：
- 出网：普通请求统一走 _http()，GET 优先借容器 self.fetch()，失败或 POST 回落 urllib，
  SSL 校验失败自动降级重试一次；投屏请求走自带客户端（保签名头 + cookie）
- 源1（默认）：JCE 25312 / bkliveinfo 双通道互备，bk 取不到回落 JCE，
  JCE 撞到死链 CDN(liverecord.video.cloud.cctv.com) 自动切 bk
- 源2（投屏）：模拟电视接收端做设备注册 + 云设备注册 + 双设备热备池，
  换高码流；启动不建会话，进「央视高码」分类或点开投屏线路时才触发
- 播放：localProxy 取代 ThreadingHTTPServer，不占端口；live_mode 可在
  代理滚动缓冲(proxy) 与 官方直连 302(redirect) 之间切换
- 入口：live(直播 M3U) / site(点播分类+详情) / diag 三种模式共用同一份频道表
- 依赖：纯标准库，内置纯 Python AES-256-GCM 与 RSA-OAEP，不需要装加解密包
"""

import base64, gzip, hashlib, hmac as _hmac, http.cookiejar, json, os, random, re, socket, struct, threading, time
import ssl
import urllib.error, urllib.parse, urllib.request, uuid
from collections import deque

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"


# ================================================================ 日志 (已禁用文件写入)
# 只 print 到 stdout, 不写文件. TVBox 一般看不到 stdout, 等于静默.

def _log(msg):
    try:
        print('[ysp] ' + msg, flush=True)
    except Exception:
        pass


def format_remarks(brand="央视频", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    return ("%s | %s" % (brand, clean_meta)) if clean_meta else brand


UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
WINDOW = 300
REFRESH_INTERVAL = 2
IDLE_TIMEOUT = 300
MAX_SEGS = 400
PLAYLIST_WINDOW = 8
HTTP_TIMEOUT = 12


# ================================================================ JCE 协议

class W:
    def __init__(self): self.b = bytearray()
    def head(self, typ, tag):
        if tag < 15: self.b.append(((tag & 0xf) << 4) | (typ & 0xf))
        else: self.b.append(0xf0 | (typ & 0xf)); self.b.append(tag)
    def byte(self, v, tag):
        v = int(v)
        if v == 0: self.head(12, tag)
        else: self.head(0, tag); self.b += struct.pack('>b', v)
    def short(self, v, tag):
        v = int(v)
        if -128 <= v <= 127: self.byte(v, tag)
        else: self.head(1, tag); self.b += struct.pack('>h', v)
    def int(self, v, tag):
        v = int(v)
        if -32768 <= v <= 32767: self.short(v, tag)
        else: self.head(2, tag); self.b += struct.pack('>i', v)
    def long(self, v, tag):
        v = int(v)
        if -2147483648 <= v <= 2147483647: self.int(v, tag)
        else: self.head(3, tag); self.b += struct.pack('>q', v)
    def float(self, v, tag):
        self.head(4, tag); self.b += struct.pack('>f', float(v))
    def double(self, v, tag):
        self.head(5, tag); self.b += struct.pack('>d', float(v))
    def string(self, s, tag):
        if s is None: return
        data = str(s).encode('utf-8')
        if len(data) > 255: self.head(7, tag); self.b += struct.pack('>i', len(data)); self.b += data
        else: self.head(6, tag); self.b.append(len(data)); self.b += data
    def bytes(self, data, tag):
        data = bytes(data); self.head(13, tag); self.head(0, 0); self.int(len(data), 0); self.b += data
    def struct(self, fn, tag): self.head(10, tag); fn(self); self.head(11, 0)
    def list(self, items, tag, wf=None): self.head(9, tag); self.int(len(items), 0)
    def out(self): return bytes(self.b)


class R:
    def __init__(self, data): self.d = memoryview(data); self.p = 0
    def rem(self): return len(self.d) - self.p
    def get(self, n):
        if self.p + n > len(self.d): raise EOFError
        b = self.d[self.p:self.p + n].tobytes(); self.p += n; return b
    def u8(self): return self.get(1)[0]
    def head(self):
        b = self.u8(); typ = b & 0xf; tag = (b & 0xf0) >> 4
        if tag == 15: tag = self.u8()
        return typ, tag
    def value(self, typ):
        if typ == 0: return struct.unpack('>b', self.get(1))[0]
        if typ == 1: return struct.unpack('>h', self.get(2))[0]
        if typ == 2: return struct.unpack('>i', self.get(4))[0]
        if typ == 3: return struct.unpack('>q', self.get(8))[0]
        if typ == 4: return struct.unpack('>f', self.get(4))[0]
        if typ == 5: return struct.unpack('>d', self.get(8))[0]
        if typ == 6: n = self.u8(); return self.get(n).decode('utf-8', 'replace')
        if typ == 7: n = struct.unpack('>i', self.get(4))[0]; return self.get(n).decode('utf-8', 'replace')
        if typ == 8: n = self._int(); return {self._fv(): self._fv() for _ in range(n)}
        if typ == 9: n = self._int(); return [self._fv() for _ in range(n)]
        if typ == 10: return self.struct()
        if typ == 11: return None
        if typ == 12: return 0
        if typ == 13: t, _ = self.head(); n = self._int(); return self.get(n)
        raise ValueError('type %d' % typ)
    def _fv(self): t, _ = self.head(); return self.value(t)
    def _int(self): t, _ = self.head(); return int(self.value(t))
    def struct(self):
        m = {}
        while self.rem() > 0:
            t, tag = self.head()
            if t == 11: break
            m[tag] = self.value(t)
        return m


VER_NAME, VER_CODE = '3.2.7.26212', '302070'
APP_ID, QMF_APP_ID, QMF_PLATFORM, BIZ_ID = '1200013', 10012, 1, 0
CHAN_ID = '10070'
GUID = ''.join(random.choice('0123456789abcdef') for _ in range(32))


def _qua(w):
    w.string(VER_NAME, 0); w.string(VER_CODE, 1)
    w.int(1080, 2); w.int(2400, 3); w.int(3, 4); w.string('12', 5)
    w.int(1, 6); w.int(1, 7); w.int(420, 8); w.string(CHAN_ID, 9)
    for i in range(10, 15): w.string('', i)
    w.struct(lambda ww: (ww.int(0, 0), ww.byte(0, 1), ww.string('', 2)), 15)
    w.string('', 16); w.string('', 17); w.string('', 18)
    w.struct(lambda ww: (ww.int(0, 0), ww.float(0, 1), ww.float(0, 2), ww.double(0, 3)), 19)
    w.string(GUID[:16], 20); w.string('Pixel 6', 21)
    w.int(1, 22)
    for i in range(23, 27): w.int(0, i)
    w.string('', 27); w.string('', 28); w.string(GUID, 29)


def _head(w, cmd, reqid):
    w.int(reqid, 0); w.int(cmd, 1)
    w.struct(lambda ww: _qua(ww), 2)
    w.string(APP_ID, 3); w.string(GUID, 4)
    w.list([], 5); w.struct(lambda ww: None, 6)
    w.list([], 7)
    w.int(0, 8); w.int(0, 9); w.int(0, 10)


def _wrap(cmd, body, reqid):
    w = W()
    w.struct(lambda ww: _head(ww, cmd, reqid), 0)
    w.bytes(body, 1)
    reqcmd = w.out()
    inner = bytearray([38]) + struct.pack('>i', len(reqcmd) + 17) + bytes([1]) + b'\x00' * 10 + reqcmd + bytes([40])
    comp = gzip.compress(bytes(inner))
    out = bytearray([19]) + struct.pack('>i', 0) + struct.pack('>H', 2) + struct.pack('>H', 65281)
    out += struct.pack('>H', cmd) + struct.pack('>H', 0) + struct.pack('>q', reqid)
    out += struct.pack('>i', 531) + struct.pack('>i', QMF_APP_ID) + struct.pack('>q', BIZ_ID)
    g = GUID.encode()[:32]; out += g + b'\x00' * (32 - len(g))
    out += struct.pack('>b', QMF_PLATFORM) + struct.pack('>i', int(VER_CODE)) + b'\x00' * 6
    out += bytes([0]) + struct.pack('>H', 0) + struct.pack('>H', 0)
    out += struct.pack('>i', len(inner)) + comp + bytes([3])
    struct.pack_into('>i', out, 1, len(out))
    return bytes(out)


def _unwrap(data):
    if data[:1] != b'\x13' or len(data) < 90: return None
    flags = struct.unpack('>i', data[21:25])[0]
    payload = data[89:-1]
    if flags & 2: payload = gzip.decompress(payload)
    if payload[:1] != b'&' or payload[-1:] != b'(': return None
    rc = R(payload[16:-1]).struct()
    return rc.get(1) or b''


class DeadHostError(RuntimeError):
    pass


def jce_timeshift_url(pid, sid, start, end, stream='fhd'):
    chk_str = (str(pid) + str(sid)).lower()
    if 'cctv11' in chk_str or '2027248701' in chk_str or '600001806' in chk_str:
        stream = 'hd'
    w = W()
    w.string(pid, 0); w.string(sid, 1); w.long(start, 2); w.long(end, 3); w.string(stream, 4)
    body = w.out()
    CMD = 25312
    reqid = int(time.time() * 1000) & 0x7fffffff
    packet = _wrap(CMD, body, reqid)
    st, raw, _ = _http('POST', 'https://jacc.ysp.cctv.cn',
                      {'Content-Type': 'application/octet-stream'}, packet, HTTP_TIMEOUT)
    if st < 200 or st >= 300:
        raise RuntimeError('jce HTTP %d' % st)
    resp_body = _unwrap(raw)
    if not resp_body: raise RuntimeError('bad response')
    m = R(resp_body).struct()
    err = m.get(0, 0)
    if err != 0: raise RuntimeError(m.get(1, 'errCode=%s' % err))
    url = m.get(2, '')
    if not url: raise RuntimeError('empty m3u8')
    if 'liverecord.video.cloud.cctv.com' in url:
        raise DeadHostError('dead cdn host')
    return url


# ================================================================ cKey + bkliveinfo

_CK_PLATFORM = 4330403
_CK_APPVER = 'V8.22.1035.3031'
_CK_TEA = bytes.fromhex('59b2f7cf725ef43c34fdd7c123411ed3')
_CK_GTEA = bytes.fromhex('110DBEC10C23E7D2E56A1CAD6914EF1B')
_CK_XOR = bytes([0x84, 0x2e, 0xed, 0x08, 0xf0, 0x66, 0xe6, 0xea, 0x48, 0xb4, 0xca, 0xa9, 0x91, 0xed, 0x6f, 0xf3])
_CK_GXOR = bytes([0xb3, 0xc9, 0x53, 0xa0, 0x69, 0x13, 0xad, 0x4d])


def _u32(v): return v & 0xFFFFFFFF


def _tea_blk(blk, key):
    y, z = struct.unpack('>2I', blk)
    k = struct.unpack('>4I', key)
    s = 0
    for _ in range(16):
        s = _u32(s + 0x9e3779b9)
        y = _u32(y + _u32(_u32(_u32(z << 4) + k[0]) ^ _u32(z + s) ^ _u32((z >> 5) + k[1])))
        z = _u32(z + _u32(_u32(_u32(y << 4) + k[2]) ^ _u32(y + s) ^ _u32((y >> 5) + k[3])))
    return struct.pack('>2I', y, z)


def _cksum(buf):
    v = 0
    for b in buf: v = (0x83 * v + b) & 0x7fffffff
    return v


def _tea_pkt(data, key):
    pad = (8 - ((len(data) + 10) % 8)) % 8
    plain = bytes([(os.urandom(1)[0] & 0xf8) | pad]) + os.urandom(pad) + os.urandom(2) + data + bytes(7)
    out, pp, pc = b'', bytes(8), bytes(8)
    for off in range(0, len(plain), 8):
        mixed = bytes(a ^ b for a, b in zip(plain[off:off + 8], pc))
        enc = _tea_blk(mixed, key)
        cipher = bytes(a ^ b for a, b in zip(enc, pp))
        out += cipher
        pp, pc = mixed, cipher
    return out


def _lp(s):
    d = s.encode() if isinstance(s, str) else s
    return struct.pack('>H', len(d)) + d


def _ck_guard(ts, guid):
    def tail(v):
        t = str(v); return t[-5:] if len(t) >= 5 else ''
    body = struct.pack('>I', ts) + _lp(tail(guid)) + _lp(tail('null')) + _lp(tail('null')) + _lp('-1')
    plain = _lp(body)
    enc = _tea_pkt(plain, _CK_GTEA) + struct.pack('>I', _cksum(plain))
    enc = bytes(a ^ _CK_GXOR[i & 7] for i, a in enumerate(enc))
    return enc.hex().upper()


def _ckey(channel_id):
    ts = int(time.time())
    guid = os.urandom(16).hex()
    guard = _ck_guard(ts, guid)
    uid = os.urandom(4).hex().upper()
    body = (bytes.fromhex('0000004200000004000004d2') + struct.pack('>I', _CK_PLATFORM)
            + struct.pack('>I', 0) + struct.pack('>I', ts) + _lp('dcgh')
            + _lp('_zj1A5Gh6QYcxWjIUGos2w==') + _lp(_CK_APPVER) + _lp(str(channel_id))
            + _lp(guid) + struct.pack('>I', 1) + struct.pack('>I', 1) + _lp(uid) + _lp('nil')
            + _lp('57eab0c4-2c58-44c6-8ae9-dd2757525dc5') + _lp('nil') + _lp('v0.1.000')
            + _lp('com.cctv.yangshipin.app.iphone') + _lp(str(_CK_PLATFORM))
            + _lp('ex_json_bus') + _lp('ex_json_vs') + _lp(guard))
    pkt = bytearray(struct.pack('>H', len(body)) + body)
    pkt[18:22] = struct.pack('>I', _cksum(bytes(pkt)))
    pkt = bytes(pkt)
    enc = _tea_pkt(pkt, _CK_TEA) + struct.pack('>I', _cksum(pkt))
    enc = bytes(a ^ _CK_XOR[i & 15] for i, a in enumerate(enc))
    b64 = base64.b64encode(enc).decode().replace('+', '_').replace('/', '-').rstrip('=')
    return {'cKey': '--01' + b64, 'guid': guid, 'ts': ts,
            'flowId': '%s_%d' % (uuid.uuid4().hex.upper(), _CK_PLATFORM)}


_BK_H264 = base64.b64encode(b'H(30:1080,60:1080|30:1080,60:1080)').decode()


def bk_playurls(channel_id, live_pid, defn='fhd'):
    chk_str = (str(channel_id) + str(live_pid)).lower()
    if 'cctv11' in chk_str or '2027248701' in chk_str or '600001806' in chk_str:
        defn = 'hd'
    t = _ckey(channel_id)
    q = urllib.parse.urlencode({
        'atime': '120', 'livepid': live_pid, 'cnlid': channel_id,
        'appVer': _CK_APPVER, 'app_version': '300090', 'caplv': '1', 'cmd': '2',
        'defn': defn, 'device': 'iPhone', 'encryptVer': '4.2', 'getpreviewinfo': '0',
        'hevclv': '0', 'lang': 'zh-Hans_CN', 'livequeue': '0', 'logintype': '1',
        'nettype': '1', 'newnettype': '1', 'newplatform': str(_CK_PLATFORM),
        'platform': str(_CK_PLATFORM), 'sdtfrom': 'v3021', 'spacode': '23',
        'spaudio': '1', 'spdemuxer': '6', 'spdrm': '2', 'spdynamicrange': '1',
        'spflv': '1', 'spflvaudio': '1', 'sphdrfps': '60', 'sphttps': '1',
        'spvcode': _BK_H264, 'spvideo': '4', 'stream': '1', 'system': '1',
        'sysver': 'ios18.2.1', 'uhd_flag': '0', 'cKey': t['cKey'], 'guid': t['guid'],
        'fntick': str(t['ts']), 'flowid': t['flowId'], 'playbacktime': '0',
    })
    st, body, _ = _http('GET', 'https://bkliveinfo.ysp.cctv.cn/?' + q,
                        {'User-Agent': 'qqlive', 'Accept': 'application/json'}, None, HTTP_TIMEOUT)
    if st < 200 or st >= 300:
        raise RuntimeError('bk HTTP %d' % st)
    p = json.loads(body.decode('utf-8', 'replace'))
    if int(p.get('iretcode', -1)) != 0:
        raise RuntimeError('iretcode=%s %s' % (p.get('iretcode'), p.get('errinfo', '')))
    urls = []
    if p.get('playurl'): urls.append(p['playurl'])
    bu = p.get('backurl_list') or p.get('backurlList') or p.get('backurl')
    if isinstance(bu, list):
        for it in bu: urls.append(it if isinstance(it, str) else (it.get('url') or it.get('playurl') or ''))
    elif isinstance(bu, str):
        urls += [x for x in re.split(r'[;,]', bu) if x.strip()]
    urls = [u for u in dict.fromkeys(urls) if u and '.cctv.' in u]
    if not urls: raise RuntimeError('no playurl')
    urls.sort(key=lambda u: (0 if 'bklive-' in u else 1, u))
    return urls


# ================================================================ 央视高码内核 (协议源自 ysp-live v9.0)

CAST_AK = '9f5c54c4ed0e50109b800f7e28fec205'
CAST_RSA_PUBKEY_B64 = ('MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAkKeLy4ywWLSnBkwRyqYgF3HMIj05V5uu'
                       'h5HjyEsZOWnu1NHu3jPQv3sr32wwQNYv5qapsNXmNgLUDHtgHZxqPQAYXltjSRc0qhcD286t62wOIH'
                       'Id8zXS3s1Jy4rgU4qjQWzI9rp/1sE0pMsmwTaJa4zuJ5iz8VwF8Av5oJ1k+HxY+/HLnjNlW1hmWLpu'
                       'DYmkZYuAoTHa1VGeHQh9FEKI8ZcL3GTQphShUoC+Kg3P1hGUVTtCYapmzPS5lkAdwebuzwvTCfGiT'
                       'ErYZCnPBUSeV7BVlgjtLYIi29KvF0a8FHsJMfe/UdHcyW/RihsIYOtDQcRRpFGXyPXbVrzFJse24'
                       'QIDAQAB')
CAST_CLOUD_GET = 'https://ytpcloudws.cctv.cn/cloudps/wssapi/device/v2/get'
CAST_CLOUD_REGISTER = 'https://ytpcloudws.cctv.cn/cloudps/wssapi/device/v2/register'
CAST_APP_START = 'https://ytpaddr.cctv.cn/gsnw/api/app/start/v1/01'
CAST_DRM_CONFIG = 'https://ytpaddr.cctv.cn/gsnw/drm/config/obtain/v1'
CAST_VERSION_CONFIG = 'https://ytpaddr.cctv.cn/gsnw/version/config/obtain/v1'
CAST_DICTIONARY = 'https://ytpaddr.cctv.cn/gsnw/player/dictionary/obtain/v1'
CAST_INDEX = 'https://ytpaddr.cctv.cn/gsnw/api/index/v1/01'
CAST_REPORT_SINGLE = 'https://ytpdata.cctv.cn/das/app/data/message/single'
CAST_COLLECT_REPORT = 'https://collect.cctv.cn/cctvmobileinf/rest/cctv/receive/new/app'
CAST_LIVE_01 = 'https://ytpaddr.cctv.cn/gsnw/api/live/v1/01'
CAST_LIVE_02 = 'https://ytpaddr.cctv.cn/gsnw/api/live/v1/02'
CAST_VDN = 'https://ytpvdn.cctv.cn/cctvmobileinf/rest/cctv/videoliveUrl/getstream'
CAST_LIVE_USER_ID = 'BAEBFF2B-C516-4F34-ABC0-A824A6461CBD'
CAST_DEVICE_NAME = '央视频电视投屏助手'
CAST_VDN_APP_NAME = '央视频电视投屏助手'
CAST_REPORT_APP_KEY = '1178c84d-4818-44ff-b415-02106e87e144'
CAST_SDK_VERSION = '1.0.0'
CAST_PAGE_NAME = 'com.cctv.tv.mvp.ui.activity.MainActivity'
CAST_ACCEPT_LANGUAGE = 'zh-CN,zh;q=0.8'
CAST_UA = 'cctv_app_tv'
CAST_APP_CHANNEL = 'dangbei'
CAST_VERSION = '1.4.1'
CAST_RESULT_OK = 0
CAST_RESULT_NEEDS_REGISTER = 601
CAST_RESULT_GET_INVALID = 2
CAST_RESULT_REGISTERED_ELSEWHERE = 694
CAST_RESULT_RETRY_LATER = 695

# ==== 纯 Python AES-256 / GCM / RSA-OAEP-SHA256（不依赖 pycryptodome、cryptography）====

_SBOX =(99 ,124 ,119 ,123 ,242 ,107 ,111 ,197 ,48 ,1 ,103 ,43 ,254 ,215 ,171 ,118 ,202 ,130 ,201 ,125 ,250 ,89 ,71 ,240 ,173 ,212 ,162 ,175 ,156 ,164 ,114 ,192 ,183 ,253 ,147 ,38 ,54 ,63 ,247 ,204 ,52 ,165 ,229 ,241 ,113 ,216 ,49 ,21 ,4 ,199 ,35 ,195 ,24 ,150 ,5 ,154 ,7 ,18 ,128 ,226 ,235 ,39 ,178 ,117 ,9 ,131 ,44 ,26 ,27 ,110 ,90 ,160 ,82 ,59 ,214 ,179 ,41 ,227 ,47 ,132 ,83 ,209 ,0 ,237 ,32 ,252 ,177 ,91 ,106 ,203 ,190 ,57 ,74 ,76 ,88 ,207 ,208 ,239 ,170 ,251 ,67 ,77 ,51 ,133 ,69 ,249 ,2 ,127 ,80 ,60 ,159 ,168 ,81 ,163 ,64 ,143 ,146 ,157 ,56 ,245 ,188 ,182 ,218 ,33 ,16 ,255 ,243 ,210 ,205 ,12 ,19 ,236 ,95 ,151 ,68 ,23 ,196 ,167 ,126 ,61 ,100 ,93 ,25 ,115 ,96 ,129 ,79 ,220 ,34 ,42 ,144 ,136 ,70 ,238 ,184 ,20 ,222 ,94 ,11 ,219 ,224 ,50 ,58 ,10 ,73 ,6 ,36 ,92 ,194 ,211 ,172 ,98 ,145 ,149 ,228 ,121 ,231 ,200 ,55 ,109 ,141 ,213 ,78 ,169 ,108 ,86 ,244 ,234 ,101 ,122 ,174 ,8 ,186 ,120 ,37 ,46 ,28 ,166 ,180 ,198 ,232 ,221 ,116 ,31 ,75 ,189 ,139 ,138 ,112 ,62 ,181 ,102 ,72 ,3 ,246 ,14 ,97 ,53 ,87 ,185 ,134 ,193 ,29 ,158 ,225 ,248 ,152 ,17 ,105 ,217 ,142 ,148 ,155 ,30 ,135 ,233 ,206 ,85 ,40 ,223 ,140 ,161 ,137 ,13 ,191 ,230 ,66 ,104 ,65 ,153 ,45 ,15 ,176 ,84 ,187 ,22 )
_INV_SBOX =[0 ]*256 
for _i ,_v in enumerate (_SBOX ):
    _INV_SBOX [_v ]=_i 
_INV_SBOX =tuple (_INV_SBOX )
_RCON =(1 ,2 ,4 ,8 ,16 ,32 ,64 ,128 ,27 ,54 )
def _xtime (a :int )->int :
    return (a <<1 ^283 )&255 if a &128 else a <<1 &255 
def _aes256_key_schedule (key :bytes ):
    assert len (key )==32 
    w =[int .from_bytes (key [i :i +4 ],'big')for i in range (0 ,32 ,4 )]
    for i in range (8 ,60 ):
        temp =w [i -1 ]
        if i %8 ==0 :
            temp =_SBOX [temp >>16 &255 ]<<24 |_SBOX [temp >>8 &255 ]<<16 |_SBOX [temp &255 ]<<8 |_SBOX [temp >>24 &255 ]
            temp ^=_RCON [i //8 -1 ]<<24 
        elif i %8 ==4 :
            temp =_SBOX [temp >>24 &255 ]<<24 |_SBOX [temp >>16 &255 ]<<16 |_SBOX [temp >>8 &255 ]<<8 |_SBOX [temp &255 ]
        w .append (w [i -8 ]^temp )
    return [b''.join ((word .to_bytes (4 ,'big')for word in w [i :i +4 ]))for i in range (0 ,60 ,4 )]
def _add_round_key (state ,rk :bytes ):
    for i in range (16 ):
        state [i ]^=rk [i ]
def _sub_bytes (state ):
    for i in range (16 ):
        state [i ]=_SBOX [state [i ]]
def _inv_sub_bytes (state ):
    for i in range (16 ):
        state [i ]=_INV_SBOX [state [i ]]
def _shift_rows (s ):
    s [1 ],s [5 ],s [9 ],s [13 ]=(s [5 ],s [9 ],s [13 ],s [1 ])
    s [2 ],s [6 ],s [10 ],s [14 ]=(s [10 ],s [14 ],s [2 ],s [6 ])
    s [3 ],s [7 ],s [11 ],s [15 ]=(s [15 ],s [3 ],s [7 ],s [11 ])
def _inv_shift_rows (s ):
    s [1 ],s [5 ],s [9 ],s [13 ]=(s [13 ],s [1 ],s [5 ],s [9 ])
    s [2 ],s [6 ],s [10 ],s [14 ]=(s [10 ],s [14 ],s [2 ],s [6 ])
    s [3 ],s [7 ],s [11 ],s [15 ]=(s [7 ],s [11 ],s [15 ],s [3 ])
def _mix_columns (s ):
    for c in range (4 ):
        a0 ,a1 ,a2 ,a3 =(s [4 *c ],s [4 *c +1 ],s [4 *c +2 ],s [4 *c +3 ])
        s [4 *c ]=_xtime (a0 )^(_xtime (a1 )^a1 )^a2 ^a3 
        s [4 *c +1 ]=a0 ^_xtime (a1 )^(_xtime (a2 )^a2 )^a3 
        s [4 *c +2 ]=a0 ^a1 ^_xtime (a2 )^(_xtime (a3 )^a3 )
        s [4 *c +3 ]=_xtime (a0 )^a0 ^a1 ^a2 ^_xtime (a3 )
def _mul (a :int ,b :int )->int :
    p =0 
    for _ in range (8 ):
        if b &1 :
            p ^=a 
        hi =a &128 
        a =a <<1 &255 
        if hi :
            a ^=27 
        b >>=1 
    return p 
def _inv_mix_columns (s ):
    for c in range (4 ):
        a0 ,a1 ,a2 ,a3 =(s [4 *c ],s [4 *c +1 ],s [4 *c +2 ],s [4 *c +3 ])
        s [4 *c ]=_mul (a0 ,14 )^_mul (a1 ,11 )^_mul (a2 ,13 )^_mul (a3 ,9 )
        s [4 *c +1 ]=_mul (a0 ,9 )^_mul (a1 ,14 )^_mul (a2 ,11 )^_mul (a3 ,13 )
        s [4 *c +2 ]=_mul (a0 ,13 )^_mul (a1 ,9 )^_mul (a2 ,14 )^_mul (a3 ,11 )
        s [4 *c +3 ]=_mul (a0 ,11 )^_mul (a1 ,13 )^_mul (a2 ,9 )^_mul (a3 ,14 )
def aes256_encrypt_block (key :bytes ,block :bytes )->bytes :
    rk =_aes256_key_schedule (key )
    s =bytearray (block )
    _add_round_key (s ,rk [0 ])
    for rnd in range (1 ,14 ):
        _sub_bytes (s )
        _shift_rows (s )
        _mix_columns (s )
        _add_round_key (s ,rk [rnd ])
    _sub_bytes (s )
    _shift_rows (s )
    _add_round_key (s ,rk [14 ])
    return bytes (s )
def aes256_decrypt_block (key :bytes ,block :bytes )->bytes :
    rk =_aes256_key_schedule (key )
    s =bytearray (block )
    _add_round_key (s ,rk [14 ])
    for rnd in range (13 ,0 ,-1 ):
        _inv_shift_rows (s )
        _inv_sub_bytes (s )
        _add_round_key (s ,rk [rnd ])
        _inv_mix_columns (s )
    _inv_shift_rows (s )
    _inv_sub_bytes (s )
    _add_round_key (s ,rk [0 ])
    return bytes (s )
def _gf_mult (x :int ,y :int )->int :
    r =299076299051606071403356588563077529600 
    z =0 
    v =y 
    for _ in range (128 ):
        if x &170141183460469231731687303715884105728 :
            z ^=v 
        if v &1 :
            v =v >>1 ^r 
        else :
            v >>=1 
        x =x <<1 &340282366920938463463374607431768211455 
    return z 
def _ghash (h :int ,aad :bytes ,ct :bytes )->int :
    x =0 
    def _blocks (data :bytes ):
        for i in range (0 ,len (data ),16 ):
            blk =data [i :i +16 ]
            if len (blk )<16 :
                blk =blk +b'\x00'*(16 -len (blk ))
            yield int .from_bytes (blk ,'big')
    for b in _blocks (aad ):
        x =_gf_mult (x ^b ,h )
    for b in _blocks (ct ):
        x =_gf_mult (x ^b ,h )
    lens =len (aad )*8 <<64 |len (ct )*8 
    x =_gf_mult (x ^lens ,h )
    return x 
def _inc32 (block :bytes )->bytes :
    ctr =int .from_bytes (block [12 :],'big')
    return block [:12 ]+(ctr +1 &4294967295 ).to_bytes (4 ,'big')
def _gctr (key :bytes ,icb :bytes ,data :bytes )->bytes :
    out =bytearray ()
    cb =icb 
    for i in range (0 ,len (data ),16 ):
        ks =aes256_encrypt_block (key ,cb )
        chunk =data [i :i +16 ]
        out +=bytes ((a ^b for a ,b in zip (chunk ,ks )))
        cb =_inc32 (cb )
    return bytes (out )
def aes_gcm_encrypt (key :bytes ,nonce :bytes ,plaintext :bytes ,aad :bytes =b'')->bytes :
    assert len (key )==32 and len (nonce )==12 
    h =int .from_bytes (aes256_encrypt_block (key ,b'\x00'*16 ),'big')
    j0 =nonce +b'\x00\x00\x00\x01'
    ct =_gctr (key ,_inc32 (j0 ),plaintext )
    s =_ghash (h ,aad ,ct ).to_bytes (16 ,'big')
    tag =bytes ((a ^b for a ,b in zip (aes256_encrypt_block (key ,j0 ),s )))
    return ct +tag 
def aes_gcm_decrypt (key :bytes ,nonce :bytes ,ct_and_tag :bytes ,aad :bytes =b'')->bytes :
    if len (ct_and_tag )<16 :
        raise ValueError ('AES-GCM payload too short')
    ct ,tag =(ct_and_tag [:-16 ],ct_and_tag [-16 :])
    h =int .from_bytes (aes256_encrypt_block (key ,b'\x00'*16 ),'big')
    j0 =nonce +b'\x00\x00\x00\x01'
    s =_ghash (h ,aad ,ct ).to_bytes (16 ,'big')
    expect =bytes ((a ^b for a ,b in zip (aes256_encrypt_block (key ,j0 ),s )))
    if not _hmac .compare_digest (tag ,expect ):
        raise ValueError ('AES-GCM decrypt failed')
    return _gctr (key ,_inc32 (j0 ),ct )
def _mgf1_sha256 (seed :bytes ,length :int )->bytes :
    out =bytearray ()
    counter =0 
    while len (out )<length :
        out +=hashlib .sha256 (seed +counter .to_bytes (4 ,'big')).digest ()
        counter +=1 
    return bytes (out [:length ])
def _oaep_encode_sha256 (message :bytes ,k :int ,seed :bytes )->bytes :
    hlen =32 
    if len (message )>k -2 *hlen -2 :
        raise ValueError ('OAEP message too long')
    lhash =hashlib .sha256 (b'').digest ()
    ps =b'\x00'*(k -len (message )-2 *hlen -2 )
    db =lhash +ps +b'\x01'+message 
    db_mask =_mgf1_sha256 (seed ,k -hlen -1 )
    masked_db =bytes ((a ^b for a ,b in zip (db ,db_mask )))
    seed_mask =_mgf1_sha256 (masked_db ,hlen )
    masked_seed =bytes ((a ^b for a ,b in zip (seed ,seed_mask )))
    return b'\x00'+masked_seed +masked_db 
def _der_read_tlv (der :bytes ,pos :int ):
    assert der [pos ]==48 ,'expected SEQUENCE'
    pos +=1 
    ln ,pos =_der_read_len (der ,pos )
    end =pos +ln 
    items =[]
    while pos <end :
        tag =der [pos ]
        pos +=1 
        ln2 ,pos =_der_read_len (der ,pos )
        items .append ((tag ,der [pos :pos +ln2 ]))
        pos +=ln2 
    return items 
def _der_read_len (der :bytes ,pos :int ):
    first =der [pos ]
    pos +=1 
    if first &128 ==0 :
        return (first ,pos )
    n =first &127 
    return (int .from_bytes (der [pos :pos +n ],'big'),pos +n )
def _der_read_int (raw :bytes )->int :
    return int .from_bytes (raw ,'big')
def parse_spki_rsa_pubkey (der :bytes ):
    outer =_der_read_tlv (der ,0 )
    bitstring =outer [1 ][1 ]
    assert bitstring [0 ]==0 
    inner =_der_read_tlv (bitstring [1 :],0 )
    n =_der_read_int (inner [0 ][1 ])
    e =_der_read_int (inner [1 ][1 ])
    return (n ,e )
def rsa_oaep_sha256_encrypt (der :bytes ,message :bytes ,seed :bytes )->bytes :
    n ,e =parse_spki_rsa_pubkey (der )
    k =(n .bit_length ()+7 )//8 
    em =_oaep_encode_sha256 (message ,k ,seed )
    m =int .from_bytes (em ,'big')
    c =pow (m ,e ,n )
    return c .to_bytes (k ,'big')


class CastError(Exception):
    pass


def _cast_log(msg):
    _log('[cast] ' + str(msg))


def _java_hashcode(s):
    h = 0
    for ch in s:
        h = ((h * 31) + ord(ch)) & 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    return h


def _java_uuid_from_hashes(msb, lsb):
    def to_u64(v):
        return v + (1 << 64) if v < 0 else v
    return '%016x%016x' % (to_u64(msb), to_u64(lsb))


def _sha1_upper(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest().upper()


def _sha256_hex(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def _md5_hex(s):
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def _native_day0_ms(now_s):
    return 86400000 * ((int(now_s) + 28800) // 86400) - 28800000


def _compute_fingerprint(x_uid, now_ms):
    day0 = _native_day0_ms(now_ms // 1000)
    return _sha256_hex(_sha256_hex(CAST_AK + x_uid + str(now_ms) + str(day0))), now_ms, day0


def _random_hex(n):
    return ''.join(random.choice('0123456789abcdef') for _ in range(n))


def _random_mac():
    parts = [0xAA, 0xBB, 0xCC, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]
    return ':'.join('%02x' % b for b in parts)


def _sanitize_profile_id(v):
    return re.sub(r'[^A-Za-z0-9]+', '_', str(v or '')).strip('_')


def _resolution_from_screen_param(sp):
    m = re.match(r'^(\d+)\*(\d+)$', str(sp or ''))
    if not m:
        return '7680*4320'
    return '%s*%s' % (m.group(1), m.group(2))


def _compact_json_bytes(value, escape_slashes):
    text = json.dumps(value, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
    if escape_slashes:
        text = text.replace('/', '\\/')
    return text.encode('utf-8')


def _normalize_aes_key(value):
    raw = value.encode('utf-8')
    return (raw + b'\x00' * 32)[:32]


def _aes_gcm_decrypt_b64(value, key):
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as e:
        raise CastError('base64 decode failed: %s' % e)
    if len(raw) <= 12:
        raise CastError('AES-GCM payload too short')
    try:
        plain = aes_gcm_decrypt(_normalize_aes_key(key), raw[:12], raw[12:])
    except ValueError:
        raise CastError('AES-GCM decrypt failed')
    return plain.decode('utf-8', 'replace')


def _aes_gcm_encrypt_b64(value, key):
    nonce = os.urandom(12)
    try:
        enc = aes_gcm_encrypt(_normalize_aes_key(key), nonce, value.encode('utf-8'))
    except ValueError:
        raise CastError('AES-GCM encrypt failed')
    return base64.b64encode(nonce + enc).decode('ascii')


def _rsa_encrypt_device_id(device_id):
    der = base64.b64decode(CAST_RSA_PUBKEY_B64)
    n, e = parse_spki_rsa_pubkey(der)
    k = (n.bit_length() + 7) // 8
    hlen = 32
    chunk = k - 2 * hlen - 2
    data = device_id.encode('utf-8')
    out = bytearray()
    for i in range(0, len(data), chunk):
        out += rsa_oaep_sha256_encrypt(der, data[i:i + chunk], os.urandom(hlen))
    return base64.b64encode(bytes(out)).decode('ascii')


def _form_urlencode_value(s):
    out = []
    for byte in s.encode('utf-8'):
        ch = chr(byte)
        if ch.isascii() and (ch.isalnum() or ch in '*-._'):
            out.append(ch)
        elif byte == 32:
            out.append('+')
        else:
            out.append('%%%02X' % byte)
    return ''.join(out)


def _form_encode(pairs):
    return '&'.join('%s=%s' % (_form_urlencode_value(k), _form_urlencode_value(v)) for k, v in pairs).encode('utf-8')


def _url_host(url):
    try:
        return urllib.parse.urlsplit(url).hostname or ''
    except ValueError:
        return ''


_CAST_CLIENT = None
_CAST_CLIENT_LOCK = threading.Lock()


def _cast_client():
    """投屏拉切片复用同一个客户端：带 cookie jar，超时/insecure 跟着 CAST 配置走。"""
    global _CAST_CLIENT
    with _CAST_CLIENT_LOCK:
        if _CAST_CLIENT is None:
            _CAST_CLIENT = CastHttp(CAST.timeout, CAST.insecure)
        else:
            _CAST_CLIENT.timeout = max(float(CAST.timeout), 0.1)
        return _CAST_CLIENT


def _needs_signed_headers(host):
    lower = (host or '').lower()
    return 'liveali' in lower or 'liveten' in lower


def _default_playback_headers(uid):
    return {'UID': uid, 'APPID': CAST_AK, 'Referer': 'api.cctv.cn', 'User-Agent': CAST_UA}


def _generate_app_random_str():
    return '%08x-0000-%04x-0000-00000000%04x' % (
        random.getrandbits(32), random.getrandbits(16), random.getrandbits(16))


def _compute_vdn_code(app_secret, random_str=None):
    r = random_str if random_str is not None else _generate_app_random_str()
    return _md5_hex('%s%s%s' % (CAST_AK, app_secret, r)), r


def _build_vdn_appcommon(version):
    return json.dumps({'adid': '', 'av': version, 'an': CAST_VDN_APP_NAME, 'ap': CAST_UA},
                      separators=(',', ':'), ensure_ascii=False, sort_keys=True)


def _parse_result_code(value):
    if isinstance(value, dict):
        for key in ('result', 'code', 'errCode', 'errcode', 'ret'):
            if key in value:
                raw = value[key]
                if isinstance(raw, bool):
                    continue
                if isinstance(raw, int):
                    return raw
                if isinstance(raw, str):
                    try:
                        return int(raw)
                    except ValueError:
                        pass
        for key in ('data', 'error', 'response'):
            if key in value:
                found = _parse_result_code(value[key])
                if found is not None:
                    return found
    return None


def _extract_guid(value):
    if isinstance(value, dict):
        data = value.get('data')
        if isinstance(data, dict):
            guid = data.get('guid')
            if isinstance(guid, str):
                return guid
    return ''


def _root_headers(version):
    return {'X-Uid': 'ROOT', 'X-Fingerprint': 'ROOT', 'X-Nonce': str(uuid.uuid4()),
            'X-Timestamp': str(int(time.time() * 1000)), 'X-Version': version, 'UID': 'ROOT',
            'Referer': 'api.cctv.cn', 'User-Agent': CAST_UA, 'appChannel': 'ROOT',
            'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip'}


# ==== 数据结构 ====

class CastProfile(object):
    __slots__ = ('android_id', 'mac', 'hardware', 'board', 'brand', 'device', 'manufacturer',
                 'model', 'product', 'tags', 'build_type', 'user', 'resolution', 'display',
                 'version_id', 'host', 'fingerprint', 'report_model')


class CastIdentity(object):
    __slots__ = ('x_uid', 'x_fingerprint', 'ts', 'headers')

    def __init__(self, x_uid, x_fingerprint, ts, headers):
        self.x_uid = x_uid
        self.x_fingerprint = x_fingerprint
        self.ts = ts
        self.headers = headers


class CastSession(object):
    __slots__ = ('profile', 'identity', 'client', 'session_key', 'cloud_guid', 'version',
                 'screen_param', 'cast_model', 'created_at', 'generation', 'linked_channels',
                 'last_heartbeat_at', 'heartbeat_count', 'last_heartbeat_error')


class CastEntry(object):
    __slots__ = ('channel', 'live_id', 'final_url', 'playback_headers', 'android_id', 'x_uid',
                 'rate', 'rate_name', 'final_host', 'refreshed_at', 'expires_at',
                 'session_generation', 'last_error')

    def fresh(self, now):
        return bool(self.final_url) and now < self.expires_at

    def stale_usable(self, now):
        return bool(self.final_url) and now < self.expires_at + CAST_STALE_GRACE


CAST_STALE_GRACE = 900.0

# ==== 设备档案池（50+ 款 8K / 4K 电视，随机抽一台冒充投屏接收端）====

CAST_DEVICE_POOL = [
    {'source': "sony_8k_pool.XR-85Z9K", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-85Z9K", 'report_model': "XR85Z9K", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2022.XR_85Z9K", 'screen_param': "7680-4320-280", 'cast_model': "XR-85Z9K"},
    {'source': "sony_8k_pool.XR-75Z9K", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-75Z9K", 'report_model': "XR75Z9K", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2022.XR_75Z9K", 'screen_param': "7680-4320-260", 'cast_model': "XR-75Z9K"},
    {'source': "sony_8k_pool.XR-85Z9J", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-85Z9J", 'report_model': "XR85Z9J", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2021.XR_85Z9J", 'screen_param': "7680-4320-280", 'cast_model': "XR-85Z9J"},
    {'source': "sony_8k_pool.XR-75Z9J", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-75Z9J", 'report_model': "XR75Z9J", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2021.XR_75Z9J", 'screen_param': "7680-4320-260", 'cast_model': "XR-75Z9J"},
    {'source': "sony_8k_pool.KD-98ZG9", 'brand': "Sony", 'manufacturer': "Sony", 'model': "KD-98ZG9", 'report_model': "KD98ZG9", 'hardware': "mt5893", 'board': "mt5893", 'version_id': "SONYTV.2019.KD_98ZG9", 'screen_param': "7680-4320-320", 'cast_model': "KD-98ZG9"},
    {'source': "sony_8k_pool.KD-85ZG9", 'brand': "Sony", 'manufacturer': "Sony", 'model': "KD-85ZG9", 'report_model': "KD85ZG9", 'hardware': "mt5893", 'board': "mt5893", 'version_id': "SONYTV.2019.KD_85ZG9", 'screen_param': "7680-4320-280", 'cast_model': "KD-85ZG9"},
    {'source': "sony_8k_pool.KD-85ZH8", 'brand': "Sony", 'manufacturer': "Sony", 'model': "KD-85ZH8", 'report_model': "KD85ZH8", 'hardware': "mt5893", 'board': "mt5893", 'version_id': "SONYTV.2020.KD_85ZH8", 'screen_param': "7680-4320-280", 'cast_model': "KD-85ZH8"},
    {'source': "sony_8k_pool.KD-75ZH8", 'brand': "Sony", 'manufacturer': "Sony", 'model': "KD-75ZH8", 'report_model': "KD75ZH8", 'hardware': "mt5893", 'board': "mt5893", 'version_id': "SONYTV.2020.KD_75ZH8", 'screen_param': "7680-4320-260", 'cast_model': "KD-75ZH8"},
    {'source': "samsung_8k_pool.QA85QN900A", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA85QN900A", 'report_model': "QA85QN900A", 'hardware': "s5e9925", 'board': "neo8k", 'version_id': "SAMSUNGTV.2021.QN900A", 'screen_param': "7680-4320-280", 'cast_model': "QA85QN900A"},
    {'source': "samsung_8k_pool.QA75QN900A", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA75QN900A", 'report_model': "QA75QN900A", 'hardware': "s5e9925", 'board': "neo8k", 'version_id': "SAMSUNGTV.2021.QN900A", 'screen_param': "7680-4320-260", 'cast_model': "QA75QN900A"},
    {'source': "samsung_8k_pool.QA85QN900B", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA85QN900B", 'report_model': "QA85QN900B", 'hardware': "s5e9925", 'board': "neo8k", 'version_id': "SAMSUNGTV.2022.QN900B", 'screen_param': "7680-4320-280", 'cast_model': "QA85QN900B"},
    {'source': "samsung_8k_pool.QA75QN900B", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA75QN900B", 'report_model': "QA75QN900B", 'hardware': "s5e9925", 'board': "neo8k", 'version_id': "SAMSUNGTV.2022.QN900B", 'screen_param': "7680-4320-260", 'cast_model': "QA75QN900B"},
    {'source': "samsung_8k_pool.QA85QN900C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA85QN900C", 'report_model': "QA85QN900C", 'hardware': "s5e9935", 'board': "neo8k", 'version_id': "SAMSUNGTV.2023.QN900C", 'screen_param': "7680-4320-280", 'cast_model': "QA85QN900C"},
    {'source': "samsung_8k_pool.QA75QN900C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA75QN900C", 'report_model': "QA75QN900C", 'hardware': "s5e9935", 'board': "neo8k", 'version_id': "SAMSUNGTV.2023.QN900C", 'screen_param': "7680-4320-260", 'cast_model': "QA75QN900C"},
    {'source': "samsung_8k_pool.QA85QN900D", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA85QN900D", 'report_model': "QA85QN900D", 'hardware': "s5e9945", 'board': "neo8k", 'version_id': "SAMSUNGTV.2024.QN900D", 'screen_param': "7680-4320-280", 'cast_model': "QA85QN900D"},
    {'source': "samsung_8k_pool.QA98QN990C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA98QN990C", 'report_model': "QA98QN990C", 'hardware': "s5e9935", 'board': "neo8k", 'version_id': "SAMSUNGTV.2023.QN990C", 'screen_param': "7680-4320-320", 'cast_model': "QA98QN990C"},
    {'source': "samsung_8k_pool.QA85QN800C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA85QN800C", 'report_model': "QA85QN800C", 'hardware': "s5e9935", 'board': "neo8k", 'version_id': "SAMSUNGTV.2023.QN800C", 'screen_param': "7680-4320-280", 'cast_model': "QA85QN800C"},
    {'source': "samsung_8k_pool.QA75QN800D", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA75QN800D", 'report_model': "QA75QN800D", 'hardware': "s5e9945", 'board': "neo8k", 'version_id': "SAMSUNGTV.2024.QN800D", 'screen_param': "7680-4320-260", 'cast_model': "QA75QN800D"},
    {'source': "lg_8k_pool.OLED88Z1PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED88Z1PCA", 'report_model': "OLED88Z1PCA", 'hardware': "alpha9gen4", 'board': "lg8k", 'version_id': "LGTV.2021.OLED88Z1", 'screen_param': "7680-4320-320", 'cast_model': "OLED88Z1PCA"},
    {'source': "lg_8k_pool.OLED77Z1PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED77Z1PCA", 'report_model': "OLED77Z1PCA", 'hardware': "alpha9gen4", 'board': "lg8k", 'version_id': "LGTV.2021.OLED77Z1", 'screen_param': "7680-4320-260", 'cast_model': "OLED77Z1PCA"},
    {'source': "lg_8k_pool.OLED88Z2PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED88Z2PCA", 'report_model': "OLED88Z2PCA", 'hardware': "alpha9gen5", 'board': "lg8k", 'version_id': "LGTV.2022.OLED88Z2", 'screen_param': "7680-4320-320", 'cast_model': "OLED88Z2PCA"},
    {'source': "lg_8k_pool.OLED77Z2PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED77Z2PCA", 'report_model': "OLED77Z2PCA", 'hardware': "alpha9gen5", 'board': "lg8k", 'version_id': "LGTV.2022.OLED77Z2", 'screen_param': "7680-4320-260", 'cast_model': "OLED77Z2PCA"},
    {'source': "lg_8k_pool.OLED88Z3PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED88Z3PCA", 'report_model': "OLED88Z3PCA", 'hardware': "alpha9gen6", 'board': "lg8k", 'version_id': "LGTV.2023.OLED88Z3", 'screen_param': "7680-4320-320", 'cast_model': "OLED88Z3PCA"},
    {'source': "lg_8k_pool.OLED77Z3PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED77Z3PCA", 'report_model': "OLED77Z3PCA", 'hardware': "alpha9gen6", 'board': "lg8k", 'version_id': "LGTV.2023.OLED77Z3", 'screen_param': "7680-4320-260", 'cast_model': "OLED77Z3PCA"},
    {'source': "lg_8k_pool.OLED88Z4PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED88Z4PCA", 'report_model': "OLED88Z4PCA", 'hardware': "alpha9gen7", 'board': "lg8k", 'version_id': "LGTV.2024.OLED88Z4", 'screen_param': "7680-4320-320", 'cast_model': "OLED88Z4PCA"},
    {'source': "lg_8k_pool.86QNED99", 'brand': "LG", 'manufacturer': "LGE", 'model': "86QNED99", 'report_model': "86QNED99", 'hardware': "alpha9gen4", 'board': "lg8k", 'version_id': "LGTV.2021.86QNED99", 'screen_param': "7680-4320-300", 'cast_model': "86QNED99"},
    {'source': "sony_4k_pool.XR-85X95K", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-85X95K", 'report_model': "XR85X95K", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2022.XR_85X95K", 'screen_param': "3840-2160-300", 'cast_model': "XR-85X95K"},
    {'source': "sony_4k_pool.XR-75X95K", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-75X95K", 'report_model': "XR75X95K", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2022.XR_75X95K", 'screen_param': "3840-2160-280", 'cast_model': "XR-75X95K"},
    {'source': "sony_4k_pool.XR-65X90K", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-65X90K", 'report_model': "XR65X90K", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2022.XR_65X90K", 'screen_param': "3840-2160-260", 'cast_model': "XR-65X90K"},
    {'source': "sony_4k_pool.XR-55X90K", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-55X90K", 'report_model': "XR55X90K", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2022.XR_55X90K", 'screen_param': "3840-2160-240", 'cast_model': "XR-55X90K"},
    {'source': "sony_4k_pool.XR-65A95K", 'brand': "Sony", 'manufacturer': "Sony", 'model': "XR-65A95K", 'report_model': "XR65A95K", 'hardware': "mt5895", 'board': "mt5895", 'version_id': "SONYTV.2022.XR_65A95K", 'screen_param': "3840-2160-260", 'cast_model': "XR-65A95K"},
    {'source': "samsung_4k_pool.QA85QN90C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA85QN90C", 'report_model': "QA85QN90C", 'hardware': "s5e9935", 'board': "neo4k", 'version_id': "SAMSUNGTV.2023.QN90C", 'screen_param': "3840-2160-300", 'cast_model': "QA85QN90C"},
    {'source': "samsung_4k_pool.QA75QN90C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA75QN90C", 'report_model': "QA75QN90C", 'hardware': "s5e9935", 'board': "neo4k", 'version_id': "SAMSUNGTV.2023.QN90C", 'screen_param': "3840-2160-280", 'cast_model': "QA75QN90C"},
    {'source': "samsung_4k_pool.QA65QN90C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA65QN90C", 'report_model': "QA65QN90C", 'hardware': "s5e9935", 'board': "neo4k", 'version_id': "SAMSUNGTV.2023.QN90C", 'screen_param': "3840-2160-260", 'cast_model': "QA65QN90C"},
    {'source': "samsung_4k_pool.QA55QN90C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA55QN90C", 'report_model': "QA55QN90C", 'hardware': "s5e9935", 'board': "neo4k", 'version_id': "SAMSUNGTV.2023.QN90C", 'screen_param': "3840-2160-240", 'cast_model': "QA55QN90C"},
    {'source': "samsung_4k_pool.QA65S95C", 'brand': "Samsung", 'manufacturer': "Samsung", 'model': "QA65S95C", 'report_model': "QA65S95C", 'hardware': "s5e9935", 'board': "oled4k", 'version_id': "SAMSUNGTV.2023.S95C", 'screen_param': "3840-2160-260", 'cast_model': "QA65S95C"},
    {'source': "lg_4k_pool.OLED83C3PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED83C3PCA", 'report_model': "OLED83C3PCA", 'hardware': "alpha9gen6", 'board': "lg4k", 'version_id': "LGTV.2023.OLED83C3", 'screen_param': "3840-2160-300", 'cast_model': "OLED83C3PCA"},
    {'source': "lg_4k_pool.OLED77C3PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED77C3PCA", 'report_model': "OLED77C3PCA", 'hardware': "alpha9gen6", 'board': "lg4k", 'version_id': "LGTV.2023.OLED77C3", 'screen_param': "3840-2160-280", 'cast_model': "OLED77C3PCA"},
    {'source': "lg_4k_pool.OLED65C3PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED65C3PCA", 'report_model': "OLED65C3PCA", 'hardware': "alpha9gen6", 'board': "lg4k", 'version_id': "LGTV.2023.OLED65C3", 'screen_param': "3840-2160-260", 'cast_model': "OLED65C3PCA"},
    {'source': "lg_4k_pool.OLED55C3PCA", 'brand': "LG", 'manufacturer': "LGE", 'model': "OLED55C3PCA", 'report_model': "OLED55C3PCA", 'hardware': "alpha9gen6", 'board': "lg4k", 'version_id': "LGTV.2023.OLED55C3", 'screen_param': "3840-2160-240", 'cast_model': "OLED55C3PCA"},
    {'source': "lg_4k_pool.86QNED90", 'brand': "LG", 'manufacturer': "LGE", 'model': "86QNED90", 'report_model': "86QNED90", 'hardware': "alpha7gen5", 'board': "lg4k", 'version_id': "LGTV.2022.86QNED90", 'screen_param': "3840-2160-300", 'cast_model': "86QNED90"},
    {'source': "tcl_8k_pool.85X925PRO", 'brand': "TCL", 'manufacturer': "TCL", 'model': "85X925 PRO", 'report_model': "85X925PRO", 'hardware': "mt9615", 'board': "tcl8k", 'version_id': "TCLTV.2021.X925PRO", 'screen_param': "7680-4320-280", 'cast_model': "85X925 PRO"},
    {'source': "tcl_8k_pool.75X925PRO", 'brand': "TCL", 'manufacturer': "TCL", 'model': "75X925 PRO", 'report_model': "75X925PRO", 'hardware': "mt9615", 'board': "tcl8k", 'version_id': "TCLTV.2021.X925PRO", 'screen_param': "7680-4320-260", 'cast_model': "75X925 PRO"},
    {'source': "tcl_4k_pool.85C845", 'brand': "TCL", 'manufacturer': "TCL", 'model': "85C845", 'report_model': "85C845", 'hardware': "mt9615", 'board': "tcl4k", 'version_id': "TCLTV.2023.C845", 'screen_param': "3840-2160-300", 'cast_model': "85C845"},
    {'source': "tcl_4k_pool.75C845", 'brand': "TCL", 'manufacturer': "TCL", 'model': "75C845", 'report_model': "75C845", 'hardware': "mt9615", 'board': "tcl4k", 'version_id': "TCLTV.2023.C845", 'screen_param': "3840-2160-280", 'cast_model': "75C845"},
    {'source': "tcl_4k_pool.65C845", 'brand': "TCL", 'manufacturer': "TCL", 'model': "65C845", 'report_model': "65C845", 'hardware': "mt9615", 'board': "tcl4k", 'version_id': "TCLTV.2023.C845", 'screen_param': "3840-2160-260", 'cast_model': "65C845"},
    {'source': "tcl_4k_pool.75C745", 'brand': "TCL", 'manufacturer': "TCL", 'model': "75C745", 'report_model': "75C745", 'hardware': "mt9615", 'board': "tcl4k", 'version_id': "TCLTV.2023.C745", 'screen_param': "3840-2160-280", 'cast_model': "75C745"},
    {'source': "tcl_4k_pool.65C745", 'brand': "TCL", 'manufacturer': "TCL", 'model': "65C745", 'report_model': "65C745", 'hardware': "mt9615", 'board': "tcl4k", 'version_id': "TCLTV.2023.C745", 'screen_param': "3840-2160-260", 'cast_model': "65C745"},
    {'source': "changhong_4k_pool.U65G7", 'brand': "CHANGHONG", 'manufacturer': "CHANGHONG", 'model': "U65G7", 'report_model': "U65G7", 'hardware': "mt9632", 'board': "changhong4k", 'version_id': "CHANGHONGTV.2022.U65G7", 'screen_param': "3840-2160-260", 'cast_model': "U65G7"},
    {'source': "changhong_4k_pool.U55G7", 'brand': "CHANGHONG", 'manufacturer': "CHANGHONG", 'model': "U55G7", 'report_model': "U55G7", 'hardware': "mt9632", 'board': "changhong4k", 'version_id': "CHANGHONGTV.2022.U55G7", 'screen_param': "3840-2160-240", 'cast_model': "U55G7"},
    {'source': "changhong_4k_pool.L55QCN1", 'brand': "CHANGHONG", 'manufacturer': "CHANGHONG", 'model': "L55QCN1", 'report_model': "L55QCN1", 'hardware': "mt9632", 'board': "changhong4k", 'version_id': "CHANGHONGTV.2021.L55QCN1", 'screen_param': "3840-2160-240", 'cast_model': "L55QCN1"},
    {'source': "changhong_4k_pool.U43QCN1", 'brand': "CHANGHONG", 'manufacturer': "CHANGHONG", 'model': "U43QCN1", 'report_model': "U43QCN1", 'hardware': "mt9632", 'board': "changhong4k", 'version_id': "CHANGHONGTV.2021.U43QCN1", 'screen_param': "3840-2160-220", 'cast_model': "U43QCN1"},
    {'source': "changhong_4k_pool.UD65YC5500UA", 'brand': "CHANGHONG", 'manufacturer': "CHANGHONG", 'model': "UD65YC5500UA", 'report_model': "UD65YC5500UA", 'hardware': "mt9632", 'board': "changhong4k", 'version_id': "CHANGHONGTV.2020.UD65YC5500UA", 'screen_param': "3840-2160-260", 'cast_model': "UD65YC5500UA"},
]


def _random_device_template(prefer_4k=False):
    if prefer_4k:
        pool_4k = [t for t in CAST_DEVICE_POOL if '8k' not in str(t.get('source', ''))]
        if pool_4k:
            return random.choice(pool_4k)
    pool = [t for t in CAST_DEVICE_POOL if '8k' in str(t.get('source', ''))]
    return random.choice(pool or CAST_DEVICE_POOL)


def _device_profile_from_template(tpl, android_id, mac):
    p = CastProfile()
    brand_id = _sanitize_profile_id(tpl['brand'])
    model_id = _sanitize_profile_id(tpl['model'])
    p.android_id = android_id
    p.mac = mac
    p.hardware = tpl['hardware']
    p.board = tpl['board']
    p.brand = tpl['brand']
    p.manufacturer = tpl['manufacturer']
    p.model = tpl['model']
    p.report_model = tpl.get('report_model') or tpl['model']
    p.device = '%s_%s' % (brand_id, model_id)
    p.product = '%s_%s' % (brand_id, model_id)
    p.tags = 'release-keys'
    p.build_type = 'user'
    p.user = 'build'
    p.resolution = _resolution_from_screen_param(tpl['screen_param'])
    p.display = '%s-user 13 %s 2024 release-keys' % (tpl['model'], tpl['version_id'])
    p.version_id = tpl['version_id']
    p.host = '%s-tv-build' % brand_id
    p.fingerprint = '%s/%s/%s:13/%s/2024:user/release-keys' % (
        tpl['manufacturer'], p.product, p.device, tpl['version_id'])
    return p


def _infer_os_version(p):
    if ':' in p.fingerprint:
        tail = p.fingerprint.split(':', 1)[1]
        if '/' in tail:
            return tail.split('/', 1)[0]
    return ''


def _infer_sdk_int(p):
    major = _infer_os_version(p).split('.')[0] if _infer_os_version(p) else ''
    return {'13': '33', '12': '31', '11': '30', '10': '29', '9': '28', '8': '26',
            '7': '24', '6': '23'}.get(major, '')


def _compute_x_uid(p):
    build = ('1698' + p.hardware + p.board + p.brand + p.device + p.manufacturer + p.model
             + p.product + p.tags + p.build_type + p.user + p.resolution + p.mac)
    uuid_part = _java_uuid_from_hashes(_java_hashcode(build), _java_hashcode(p.model))
    return _sha1_upper('%s|%s' % (p.android_id, uuid_part))


def _build_identity(p, app_channel, version):
    x_uid = _compute_x_uid(p)
    fp, ts, _day0 = _compute_fingerprint(x_uid, int(time.time() * 1000))
    headers = {
        'Accept': 'application/json', 'Accept-Language': CAST_ACCEPT_LANGUAGE,
        'Referer': 'api.cctv.cn', 'User-Agent': CAST_UA, 'UID': p.android_id,
        'appChannel': app_channel, 'X-Uid': x_uid, 'X-Fingerprint': fp,
        'X-Version': version, 'Content-Type': 'application/json; charset=utf-8',
        'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip', 'Cache-Control': 'no-cache',
    }
    return CastIdentity(x_uid, fp, ts, headers)


def _fresh_headers(template, content_type, accept=None, force_ts=None):
    headers = {}
    if accept is not None:
        
