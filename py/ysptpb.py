# -*- coding: utf-8 -*-
"""
TVBox Py 插件 —— 央视频点播
对应配置：
{
    "key": "py_ysptp",
    "name": "央视频tp",
    "type": 3,
    "api": "./ysptpb.py",
    "searchable": 1,
    "quickSearch": 1,
    "filterable": 1,
    "epg": "https://epg.tv.darwinchow.com/epg.xml.gz",
    "catchup": {
        "type": "append",
        "source": "&playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}"
    }
}
"""

import sys
import os
import time
import json
import random
import struct
import binascii
import hashlib
import base64
import ssl
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

# ========== BaseSpider 兼容 ==========
try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def getProxyUrl(self):
            return "http://127.0.0.1:9978/proxy?do=py&"
        def init(self, extend=""): pass
        def getName(self): return "央视频"
        def liveContent(self, url): return ""
        def localProxy(self, params): return []
        def destroy(self): return ""

# ========== 日志 ==========
LOG_FILE = '/sdcard/Download/ysptpb.log'
def log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass
    try:
        print('[ysptp] ' + str(msg))
    except Exception:
        pass

# ========== CKeyManager（央视频加密） ==========
class CKeyManager:
    DELTA = 0x9e3779b9
    ROUNDS = 16
    LOG_ROUNDS = 4
    SALT_LEN = 2
    ZERO_LEN = 7
    TEA_CKEY = binascii.unhexlify('59b2f7cf725ef43c34fdd7c123411ed3')
    GUARD_TEA_KEY = binascii.unhexlify('110DBEC10C23E7D2E56A1CAD6914EF1B')

    def __init__(self):
        self.xorKey = bytes([0x84, 0x2E, 0xED, 0x08, 0xF0, 0x66, 0xE6, 0xEA,
                             0x48, 0xB4, 0xCA, 0xA9, 0x91, 0xED, 0x6F, 0xF3])
        self.guardXorKey = bytes([0xB3, 0xC9, 0x53, 0xA0, 0x69, 0x13, 0xAD, 0x4D])
        self.standardAlphabet = ('ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                 'abcdefghijklmnopqrstuvwxyz0123456789+/=')
        self.customAlphabet = ('ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                               'abcdefghijklmnopqrstuvwxyz0123456789_-=')
        self.guid = ''
        self.generate_guid()

    def generate_guid(self):
        parts = [
            format(random.getrandbits(32), '08x'),
            format(random.getrandbits(16), '04x'),
            format(random.getrandbits(16), '04x'),
            format(random.getrandbits(16), '04x'),
            format(random.getrandbits(48), '012x'),
        ]
        self.guid = ''.join(parts)
        if len(self.guid) != 32:
            self.guid = self.guid.ljust(32, '0')
        return self.guid

    @staticmethod
    def calc_signature(buffer_bytes):
        sig = 0
        for b in buffer_bytes:
            sig = (0x83 * sig + b) & 0x7FFFFFFF
        return sig

    def custom_decode(self, text):
        if not text:
            return b''
        text = text.rstrip('=')
        if len(text) % 4 != 0:
            text += '=' * (4 - len(text) % 4)
        trans = str.maketrans(self.customAlphabet[:64], self.standardAlphabet[:64])
        return base64.b64decode(text.translate(trans))

    def custom_encode(self, data):
        encoded = base64.b64encode(data).decode()
        trans = str.maketrans(self.standardAlphabet[:64], self.customAlphabet[:64])
        return encoded.translate(trans).rstrip('=')

    def xor_array(self, byte_array):
        if isinstance(byte_array, bytes):
            byte_array = list(byte_array)
        result = bytearray(len(byte_array))
        for i, b in enumerate(byte_array):
            result[i] = b ^ self.xorKey[i & 0xF]
        return bytes(result)

    def tea_encrypt_ecb(self, p_in_buf, p_key):
        if len(p_in_buf) < 8:
            p_in_buf = p_in_buf.ljust(8, b'\0')
        y, z = struct.unpack('>2I', p_in_buf[:8])
        k = struct.unpack('>4I', p_key[:16])
        s = 0
        for _ in range(self.ROUNDS):
            s = (s + self.DELTA) & 0xFFFFFFFF
            y = (y + (((z << 4) + k[0]) ^ (z + s) ^ ((z >> 5) + k[1]))) & 0xFFFFFFFF
            z = (z + (((y << 4) + k[2]) ^ (y + s) ^ ((y >> 5) + k[3]))) & 0xFFFFFFFF
        return struct.pack('>2I', y, z)

    def tea_decrypt_ecb(self, p_in_buf, p_key):
        y, z = struct.unpack('>2I', p_in_buf[:8])
        k = struct.unpack('>4I', p_key[:16])
        s = (self.DELTA << self.LOG_ROUNDS) & 0xFFFFFFFF
        for _ in range(self.ROUNDS):
            z = (z - (((y << 4) + k[2]) ^ (y + s) ^ ((y >> 5) + k[3]))) & 0xFFFFFFFF
            y = (y - (((z << 4) + k[0]) ^ (z + s) ^ ((z >> 5) + k[1]))) & 0xFFFFFFFF
            s = (s - self.DELTA) & 0xFFFFFFFF
        return struct.pack('>2I', y, z)

    def oi_symmetry_encrypt2(self, p_in_buf, n_in_buf_len, p_key):
        n_pad_salt_body_zero_len = n_in_buf_len + 1 + self.SALT_LEN + self.ZERO_LEN
        n_pad_len = n_pad_salt_body_zero_len % 8
        if n_pad_len:
            n_pad_len = 8 - n_pad_len

        p_out_buf = bytearray()
        src_buf = bytearray(8)
        src_buf[0] = (random.randint(0, 255) & 0xF8) | n_pad_len
        src_i = 1
        while n_pad_len:
            src_buf[src_i] = random.randint(0, 255)
            src_i += 1
            n_pad_len -= 1

        iv_plain = bytearray(8)
        iv_crypt = bytearray(8)

        def _flush():
            nonlocal src_buf, iv_plain, iv_crypt, src_i
            for j in range(8):
                src_buf[j] ^= iv_crypt[j]
            tmp = list(self.tea_encrypt_ecb(bytes(src_buf), p_key))
            for j in range(8):
                tmp[j] ^= iv_plain[j]
            iv_plain = src_buf[:]
            iv_crypt = bytes(tmp)
            p_out_buf.extend(tmp)
            src_buf = bytearray(8)
            src_i = 0

        i = 0
        while i < self.SALT_LEN:
            if src_i < 8:
                src_buf[src_i] = random.randint(0, 255)
                src_i += 1
                i += 1
            if src_i == 8:
                _flush()

        p_in_buf_index = 0
        while n_in_buf_len:
            if src_i < 8:
                src_buf[src_i] = p_in_buf[p_in_buf_index]
                p_in_buf_index += 1
                src_i += 1
                n_in_buf_len -= 1
            if src_i == 8:
                _flush()

        i = 0
        while i < self.ZERO_LEN:
            if src_i < 8:
                src_buf[src_i] = 0
                src_i += 1
                i += 1
            if src_i == 8:
                _flush()

        if src_i > 0:
            for j in range(src_i, 8):
                src_buf[j] = 0
            _flush()

        return bytes(p_out_buf)

    @staticmethod
    def guard_last_five(value):
        s = str(value)
        return s[-5:] if len(s) >= 5 else ''

    def generate_ck_guard_time(self, timestamp, guid, guard_data='-1',
                               package_name='null', process_name='null'):
        body = struct.pack('>I', timestamp)
        for part in [self.guard_last_five(guid),
                     self.guard_last_five(package_name),
                     self.guard_last_five(process_name),
                     guard_data]:
            body += struct.pack('>H', len(part)) + part.encode('utf-8')
        plain = struct.pack('>H', len(body)) + body
        checksum = self.calc_signature(plain)
        enc = self.oi_symmetry_encrypt2(plain, len(plain), self.GUARD_TEA_KEY)
        enc += struct.pack('>I', checksum)
        bl = list(enc)
        for i in range(len(bl)):
            bl[i] ^= self.guardXorKey[i & 7]
        return binascii.hexlify(bytes(bl)).decode().upper()

    def encrypt_data_to_ckey(self, data):
        data_len = len(data)
        checksum = self.calc_signature(data)
        enc = self.oi_symmetry_encrypt2(data, data_len, self.TEA_CKEY)
        enc += struct.pack('>I', checksum)
        return "--01" + self.custom_encode(self.xor_array(enc))

    def build_packet(self, params):
        data = bytearray(binascii.unhexlify('0000004200000004000004d2'))
        data += struct.pack('>I', params['Platform'])
        data += struct.pack('>I', 0)
        data += struct.pack('>I', params['Timestamp'])
        for key in ['Sdtfrom', 'randFlag', 'appVer', 'vid', 'guid']:
            val = params[key].encode('utf-8')
            data += struct.pack('>H', len(val)) + val
        data += struct.pack('>I', 1)
        data += struct.pack('>I', 1)
        uid = "2622783A".encode('utf-8')
        data += struct.pack('>H', len(uid)) + uid
        bundleID = "nil".encode('utf-8')
        data += struct.pack('>H', len(bundleID)) + bundleID
        uuid4 = params['uuid4'].encode('utf-8')
        data += struct.pack('>H', len(uuid4)) + uuid4
        data += struct.pack('>H', len(bundleID)) + bundleID
        ckeyVersion = "v0.1.000".encode('utf-8')
        data += struct.pack('>H', len(ckeyVersion)) + ckeyVersion
        packageName = "com.cctv.yangshipin.app.iphone".encode('utf-8')
        data += struct.pack('>H', len(packageName)) + packageName
        platform_str = "4330403".encode('utf-8')
        data += struct.pack('>H', len(platform_str)) + platform_str
        ex_json_bus = "ex_json_bus".encode('utf-8')
        data += struct.pack('>H', len(ex_json_bus)) + ex_json_bus
        ex_json_vs = "ex_json_vs".encode('utf-8')
        data += struct.pack('>H', len(ex_json_vs)) + ex_json_vs
        ck_guard_time = params['ck_guard_time'].encode('utf-8')
        data += struct.pack('>H', len(ck_guard_time)) + ck_guard_time

        body_length = len(data)
        buffer = struct.pack('>H', body_length) + data
        signature = self.calc_signature(buffer)
        buffer = buffer[:18] + struct.pack('>I', signature) + buffer[22:]
        return buffer

    def generate_ckey(self, cnlid, timestamp=None):
        if timestamp is None:
            timestamp = int(time.time())
        randFlag = base64.b64encode(os.urandom(18)).decode()
        uuid4 = (format(random.getrandbits(16), '04x') + format(random.getrandbits(16), '04x') + '-' +
                 format(random.getrandbits(16), '04x') + '-' +
                 format(random.getrandbits(16), '04x') + '-' +
                 format(random.getrandbits(16), '04x') + '-' +
                 format(random.getrandbits(16), '04x') + format(random.getrandbits(16), '04x') +
                 format(random.getrandbits(16), '04x'))
        ck_guard_time = self.generate_ck_guard_time(timestamp, self.guid)
        params = {
            'Platform': 4330403,
            'Timestamp': timestamp,
            'Sdtfrom': 'dcgh',
            'vid': cnlid,
            'guid': self.guid,
            'appVer': 'V8.22.1035.3031',
            'randFlag': randFlag,
            'uuid4': uuid4,
            'ck_guard_time': ck_guard_time,
        }
        return {'ckey': self.encrypt_data_to_ckey(self.build_packet(params)),
                'params': params}

    def build_live_params(self, cnlid, livepid, defn):
        self.generate_guid()
        ckey_result = self.generate_ckey(cnlid)
        ckey = ckey_result['ckey']
        params = ckey_result['params']
        flowid = (format(random.getrandbits(16), '04X') + format(random.getrandbits(16), '04X') + '-' +
                  format(random.getrandbits(16), '04X') + '-' +
                  format(random.getrandbits(16), '04X') + '-' +
                  format(random.getrandbits(16), '04X') + '-' +
                  format(random.getrandbits(16), '04X') + format(random.getrandbits(16), '04X') +
                  format(random.getrandbits(16), '04X') + '_4330403')
        spvcode = ("MSgzMDoyMTYwLDYwOjIxNjB8MzA6MjE2MCw2MDoyMTYwKTsyKDMwOjIxNjAs"
                   "NjA6MjE2MHwzMDoyMTYwLDYwOjIxNjAp")
        return {
            "atime": "120", "livepid": livepid, "cnlid": cnlid,
            "appVer": "V8.22.1035.3031", "app_version": "300090",
            "caplv": "1", "cmd": "2", "defn": defn, "device": "iPhone",
            "encryptVer": "4.2", "getpreviewinfo": "0", "hevclv": "33",
            "lang": "zh-Hans_JP", "livequeue": "0", "logintype": "1",
            "nettype": "1", "newnettype": "1", "newplatform": "4330403",
            "platform": "4330403", "sdtfrom": "v3021", "spacode": "23",
            "spaudio": "1", "spdemuxer": "6", "spdrm": "2",
            "spdynamicrange": "7", "spflv": "1", "spflvaudio": "1",
            "sphdrfps": "60", "sphttps": "0", "spvcode": spvcode,
            "spvideo": "4", "stream": "1", "system": "1",
            "sysver": "ios18.2.1", "uhd_flag": "4", "cKey": ckey,
            "guid": self.guid, "fntick": str(params['Timestamp']),
            "flowid": flowid, "playbacktime": "0",
        }


# ========== 频道数据 ==========
YSP_CHANNELS = {
    'cctv1':     {'name': 'CCTV1',           'cnlid': '2024078201', 'livepid': '600001859', 'defn': 'fhd'},
    'cctv2':     {'name': 'CCTV2',           'cnlid': '2024075401', 'livepid': '600001800', 'defn': 'fhd'},
    'cctv3':     {'name': 'CCTV3',           'cnlid': '2024068501', 'livepid': '600001801', 'defn': 'fhd'},
    'cctv4':     {'name': 'CCTV4',           'cnlid': '2029797101', 'livepid': '600001814', 'defn': 'fhd'},
    'cctv5':     {'name': 'CCTV5',           'cnlid': '2024078401', 'livepid': '600001818', 'defn': 'fhd'},
    'cctv5p':    {'name': 'CCTV5+',          'cnlid': '2024078001', 'livepid': '600001817', 'defn': 'fhd'},
    'cctv6':     {'name': 'CCTV6',           'cnlid': '2013693901', 'livepid': '600108442', 'defn': 'fhd'},
    'cctv7':     {'name': 'CCTV7',           'cnlid': '2024072001', 'livepid': '600004092', 'defn': 'fhd'},
    'cctv8':     {'name': 'CCTV8',           'cnlid': '2029793001', 'livepid': '600001803', 'defn': 'fhd'},
    'cctv9':     {'name': 'CCTV9',           'cnlid': '2024078601', 'livepid': '600004078', 'defn': 'fhd'},
    'cctv10':    {'name': 'CCTV10',          'cnlid': '2024078701', 'livepid': '600001805', 'defn': 'fhd'},
    'cctv11':    {'name': 'CCTV11',          'cnlid': '2027248701', 'livepid': '600001806', 'defn': 'fhd'},
    'cctv12':    {'name': 'CCTV12',          'cnlid': '2027248801', 'livepid': '600001807', 'defn': 'fhd'},
    'cctv13':    {'name': 'CCTV13',          'cnlid': '2029797201', 'livepid': '600001811', 'defn': 'fhd'},
    'cctv14':    {'name': 'CCTV14',          'cnlid': '2027248901', 'livepid': '600001809', 'defn': 'fhd'},
    'cctv15':    {'name': 'CCTV15',          'cnlid': '2027249001', 'livepid': '600001815', 'defn': 'fhd'},
    'cctv16':    {'name': 'CCTV16',          'cnlid': '2027249101', 'livepid': '600098637', 'defn': 'fhd'},
    'cctv164k':  {'name': 'CCTV16(4K)',      'cnlid': '2027249301', 'livepid': '600099502', 'defn': 'fhd'},
    'cctv17':    {'name': 'CCTV17',          'cnlid': '2027249401', 'livepid': '600001810', 'defn': 'fhd'},
    'cctv4k':    {'name': 'CCTV4K',          'cnlid': '2029810301', 'livepid': '600002264', 'defn': 'fhd'},
    'cctv8k':    {'name': 'CCTV8K',          'cnlid': '2026774101', 'livepid': '600156816', 'defn': 'fhd'},
    'cgtn':      {'name': 'CGTN',            'cnlid': '2024181701', 'livepid': '600014550', 'defn': 'fhd'},
    'cgtnfy':    {'name': 'CGTN法语',        'cnlid': '2024181801', 'livepid': '600084704', 'defn': 'fhd'},
    'cgtney':    {'name': 'CGTN俄语',        'cnlid': '2024181901', 'livepid': '600084758', 'defn': 'fhd'},
    'cgtnalby':  {'name': 'CGTN阿语',        'cnlid': '2024182001', 'livepid': '600084782', 'defn': 'fhd'},
    'cgtnxby':   {'name': 'CGTN西语',        'cnlid': '2024182101', 'livepid': '600084744', 'defn': 'fhd'},
    'cgtnwyjl':  {'name': 'CGTN纪录',        'cnlid': '2024182301', 'livepid': '600084781', 'defn': 'fhd'},
    'cctvfyjc':  {'name': '风云剧场',        'cnlid': '2025637103', 'livepid': '600099658', 'defn': 'shd'},
    'cctvdyjc':  {'name': '第一剧场',        'cnlid': '2026874203', 'livepid': '600099655', 'defn': 'shd'},
    'cctvhjjc':  {'name': '怀旧剧场',        'cnlid': '2026874303', 'livepid': '600099620', 'defn': 'shd'},
    'cctvsjdl':  {'name': '世界地理',        'cnlid': '2026874403', 'livepid': '600099637', 'defn': 'shd'},
    'cctvfyyy':  {'name': '风云音乐',        'cnlid': '2026874503', 'livepid': '600099660', 'defn': 'shd'},
    'cctvbqkj':  {'name': '兵器科技',        'cnlid': '2026874603', 'livepid': '600099649', 'defn': 'shd'},
    'cctvfyzq':  {'name': '风云足球',        'cnlid': '2026966203', 'livepid': '600099636', 'defn': 'shd'},
    'cctvgeqwq': {'name': '高尔夫网球',      'cnlid': '2026874703', 'livepid': '600099659', 'defn': 'shd'},
    'cctvnxss':  {'name': '女性时尚',        'cnlid': '2026874803', 'livepid': '600099650', 'defn': 'shd'},
    'cctvyswhjp':{'name': '央视文化精品',    'cnlid': '2026874903', 'livepid': '600099653', 'defn': 'shd'},
    'cctvystq':  {'name': '央视台球',        'cnlid': '2026875003', 'livepid': '600099652', 'defn': 'shd'},
    'cctvdszn':  {'name': '电视指南',        'cnlid': '2026875103', 'livepid': '600099656', 'defn': 'shd'},
    'cctvwsjk':  {'name': '卫生健康',        'cnlid': '2025637003', 'livepid': '600099651', 'defn': 'shd'},
    'bjws':      {'name': '北京卫视',        'cnlid': '2024052703', 'livepid': '600002309', 'defn': 'fhd'},
    'jsws':      {'name': '江苏卫视',        'cnlid': '2024171103', 'livepid': '600002521', 'defn': 'fhd'},
    'dfws':      {'name': '东方卫视',        'cnlid': '2024054503', 'livepid': '600002483', 'defn': 'fhd'},
    'zjws':      {'name': '浙江卫视',        'cnlid': '2024054703', 'livepid': '600002520', 'defn': 'fhd'},
    'hnws':      {'name': '湖南卫视',        'cnlid': '2024054803', 'livepid': '600002475', 'defn': 'fhd'},
    'hbws':      {'name': '湖北卫视',        'cnlid': '2024171203', 'livepid': '600002508', 'defn': 'fhd'},
    'gdws':      {'name': '广东卫视',        'cnlid': '2024060903', 'livepid': '600002485', 'defn': 'fhd'},
    'gxws':      {'name': '广西卫视',        'cnlid': '2024060703', 'livepid': '600002509', 'defn': 'fhd'},
    'hljws':     {'name': '黑龙江卫视',      'cnlid': '2029797003', 'livepid': '600002498', 'defn': 'fhd'},
    'hnws2':     {'name': '海南卫视',        'cnlid': '2024055603', 'livepid': '600002506', 'defn': 'fhd'},
    'cqws':      {'name': '重庆卫视',        'cnlid': '2024061103', 'livepid': '600002531', 'defn': 'fhd'},
    'szws':      {'name': '深圳卫视',        'cnlid': '2024061303', 'livepid': '600002481', 'defn': 'fhd'},
    'scws':      {'name': '四川卫视',        'cnlid': '2024061403', 'livepid': '600002516', 'defn': 'fhd'},
    'henanws':   {'name': '河南卫视',        'cnlid': '2029797303', 'livepid': '600002525', 'defn': 'fhd'},
    'fjdnhz':    {'name': '东南卫视',        'cnlid': '2024061503', 'livepid': '600002484', 'defn': 'fhd'},
    'gzhws':     {'name': '贵州卫视',        'cnlid': '2024061603', 'livepid': '600002490', 'defn': 'fhd'},
    'jxws':      {'name': '江西卫视',        'cnlid': '2024061703', 'livepid': '600002503', 'defn': 'fhd'},
    'lnws':      {'name': '辽宁卫视',        'cnlid': '2024171303', 'livepid': '600002505', 'defn': 'fhd'},
    'ahws':      {'name': '安徽卫视',        'cnlid': '2024171403', 'livepid': '600002532', 'defn': 'fhd'},
    'hbws2':     {'name': '河北卫视',        'cnlid': '2024171503', 'livepid': '600002493', 'defn': 'fhd'},
    'sdws':      {'name': '山东卫视',        'cnlid': '2029787903', 'livepid': '600002513', 'defn': 'fhd'},
    'tjws':      {'name': '天津卫视',        'cnlid': '2019927003', 'livepid': '600152137', 'defn': 'fhd'},
    'jlws':      {'name': '吉林卫视',        'cnlid': '2025561503', 'livepid': '600190405', 'defn': 'fhd'},
    'shanxiws':  {'name': '陕西卫视',        'cnlid': '2029795103', 'livepid': '600190400', 'defn': 'fhd'},
    'nxws':      {'name': '宁夏卫视',        'cnlid': '2025608503', 'livepid': '600190737', 'defn': 'fhd'},
    'nmgws':     {'name': '内蒙古卫视',      'cnlid': '2025561203', 'livepid': '600190401', 'defn': 'fhd'},
    'ynws':      {'name': '云南卫视',        'cnlid': '2025561303', 'livepid': '600190402', 'defn': 'fhd'},
    'shanxiws2': {'name': '山西卫视',        'cnlid': '2025560803', 'livepid': '600190407', 'defn': 'fhd'},
    'qhws':      {'name': '青海卫视',        'cnlid': '2025559103', 'livepid': '600190406', 'defn': 'fhd'},
    'xzws':      {'name': '西藏卫视',        'cnlid': '2025558003', 'livepid': '600190403', 'defn': 'fhd'},
    'cetv1':     {'name': '中国教育1台',     'cnlid': '2022823801', 'livepid': '600171827', 'defn': 'fhd'},
    'gxpd':      {'name': '国学频道',        'cnlid': '2029360403', 'livepid': '600213139', 'defn': 'fhd'},
    'xjws':      {'name': '新疆卫视',        'cnlid': '2019927403', 'livepid': '600152138', 'defn': 'fhd'},
}

YSP_CHANNEL_GROUPS = {
    '央视': ['cctv1','cctv2','cctv3','cctv4','cctv5','cctv5p','cctv6','cctv7',
            'cctv8','cctv9','cctv10','cctv11','cctv12','cctv13','cctv14',
            'cctv15','cctv16','cctv164k','cctv17','cctv4k','cctv8k',
            'cgtn','cgtnfy','cgtney','cgtnalby','cgtnxby','cgtnwyjl'],
    '卫视': ['bjws','jsws','dfws','zjws','hnws','hbws','gdws','gxws',
            'hljws','hnws2','cqws','szws','scws','henanws','fjdnhz',
            'gzhws','jxws','lnws','ahws','hbws2','sdws','tjws','jlws',
            'shanxiws','nxws','nmgws','ynws','shanxiws2','qhws','xzws',
            'cetv1','xjws'],
    '数字付费': ['cctvfyjc','cctvdyjc','cctvhjjc','cctvsjdl','cctvfyyy',
                'cctvbqkj','cctvfyzq','cctvgeqwq','cctvnxss','cctvyswhjp',
                'cctvystq','cctvdszn','cctvwsjk','gxpd'],
}

YSP_LIVE_API = "https://bkliveinfo.ysp.cctv.cn"


# ========== Spider ==========
class Spider(BaseSpider):
    def __init__(self):
        log("Spider 实例化成功")
        self._cache = {}  # pid -> (url, timestamp)
        self._cache_ttl = 80

    def getName(self):
        return "央视频"

    def init(self, extend=""):
        log("init 被调用 extend=%s" % (extend,))

    # ---------- HTTP ----------
    def _http_get(self, url, headers=None, timeout=15):
        if headers is None:
            headers = {}
        # 优先用 TVBox 自带 fetch
        if hasattr(self, 'fetch'):
            try:
                resp = self.fetch(url, headers=headers, timeout=timeout)
                if hasattr(resp, 'text'):
                    return resp.text
                if hasattr(resp, 'content'):
                    return resp.content.decode('utf-8', errors='ignore')
                if resp is not None:
                    return str(resp)
            except Exception as e:
                log("self.fetch 失败: %s" % e)
        # 回退 urllib
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            log("urllib 请求失败: %s" % e)
            return None

    # ---------- 获取播放地址 ----------
    def _get_play_url(self, ch, playseek=None):
        pid = ch.get('cnlid') + '|' + ch.get('livepid')
        is_live = (playseek is None or playseek == '')

        # 直播 80 秒缓存
        if is_live and pid in self._cache:
            url, ts = self._cache[pid]
            if time.time() - ts <= self._cache_ttl:
                log("缓存命中: %s" % ch['name'])
                return url

        try:
            mgr = CKeyManager()
            params = mgr.build_live_params(ch['cnlid'], ch['livepid'], ch['defn'])
            if playseek:
                # 回看：playseek = 20240101120000-20240101130000
                parts = playseek.split('-')
                if parts and len(parts[0]) >= 14:
                    dt = time.strptime(parts[0][:14], '%Y%m%d%H%M%S')
                    params['playbacktime'] = str(int(time.mktime(dt)))
            url = YSP_LIVE_API + "?" + urllib.parse.urlencode(params)
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
                'Accept': 'application/json',
            }
            text = self._http_get(url, headers, timeout=15)
            if not text:
                log("获取接口返回空")
                return None
            data = json.loads(text)
            if data.get('iretcode') == 0:
                playurl = data.get('playurl')
                if playurl:
                    log("获取播放地址成功: %s" % ch['name'])
                    if is_live:
                        self._cache[pid] = (playurl, time.time())
                    return playurl
            log("接口错误: iretcode=%s msg=%s" % (data.get('iretcode'), data.get('msg')))
        except Exception as e:
            log("_get_play_url 异常: %s" % e)
        return None

    # ---------- 点播接口 ----------
    def homeContent(self, filter):
        log("homeContent 被调用")
        classes = [{'type_id': k, 'type_name': k} for k in YSP_CHANNEL_GROUPS.keys()]
        return {'class': classes}

    def categoryContent(self, tid, pg, filter, extend):
        log("categoryContent tid=%s pg=%s" % (tid, pg))
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        size = 50
        ids = YSP_CHANNEL_GROUPS.get(tid, [])
        total = len(ids)
        start = (pg - 1) * size
        end = min(start + size, total)
        videos = []
        for pid in ids[start:end]:
            ch = YSP_CHANNELS.get(pid)
            if ch:
                videos.append({
                    'vod_id': pid,
                    'vod_name': ch['name'],
                    'vod_pic': '',
                    'vod_remarks': '直播',
                })
        return {
            'list': videos,
            'page': pg,
            'pagecount': (total + size - 1) // size,
            'limit': size,
            'total': total,
        }

    def detailContent(self, ids):
        log("detailContent ids=%s" % (ids,))
        pid = ids[0] if ids else ''
        ch = YSP_CHANNELS.get(pid)
        if not ch:
            return {'list': []}
        return {
            'list': [{
                'vod_id': pid,
                'vod_name': ch['name'],
                'vod_pic': '',
                'vod_remarks': '直播',
                'vod_content': '央视频直播',
                'vod_play_from': '央视频',
                'vod_play_url': '播放$' + pid,
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        log("playerContent flag=%s id=%s" % (flag, id))
        # id 可能是 "pid" 或 "pid$playseek"
        playseek = None
        pid = id
        if '$' in id:
            parts = id.split('$')
            pid = parts[0]
            if len(parts) > 1:
                playseek = parts[1]
        if '&playseek=' in id:
            pid, _, ps = id.partition('&playseek=')
            playseek = ps

        ch = YSP_CHANNELS.get(pid)
        if not ch:
            log("频道不存在: %s" % pid)
            return {'url': '', 'parse': 0, 'jx': 0}

        url = self._get_play_url(ch, playseek)
        if not url:
            log("获取播放地址失败")
            return {'url': '', 'parse': 0, 'jx': 0}

        return {
            'parse': 0,
            'jx': 0,
            'url': url,
            'header': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
                'Referer': 'https://ysp.cctv.cn/',
            },
        }

    def searchContent(self, key, quick, pg=1):
        log("searchContent key=%s" % key)
        videos = []
        k = (key or '').lower()
        for pid, ch in YSP_CHANNELS.items():
            if (k in ch['name'].lower()) or (k in pid.lower()):
                videos.append({
                    'vod_id': pid,
                    'vod_name': ch['name'],
                    'vod_pic': '',
                    'vod_remarks': '直播',
                })
        return {'list': videos}

    # ---------- 直播接口 ----------
    def liveContent(self, url):
        log("liveContent 被调用")
        try:
            lines = ['#EXTM3U']
            base_proxy = self.getProxyUrl()
            if not base_proxy.endswith(('?', '&')):
                base_proxy += '&'
            for group_name, ids in YSP_CHANNEL_GROUPS.items():
                lines.append('')
                lines.append('# ' + group_name)
                for pid in ids:
                    if pid in YSP_CHANNELS:
                        ch = YSP_CHANNELS[pid]
                        lines.append(
                            '#EXTINF:-1 tvg-id="%s" tvg-name="%s" group-title="%s",%s'
                            % (ch['name'], ch['name'], group_name, ch['name'])
                        )
                        lines.append(base_proxy + 'fun=cctv&id=' + pid)
            return '\n'.join(lines)
        except Exception as e:
            log("liveContent 异常: %s" % e)
            return "#EXTM3U\n"

    def localProxy(self, params):
        # TVBox 会调用，参数在 params['fun']、params['id']
        fun = params.get('fun')
        if fun == 'cctv':
            pid = params.get('id')
            ch = YSP_CHANNELS.get(pid)
            if not ch:
                return [404, 'text/plain', 'not found']
            url = self._get_play_url(ch)
            if not url:
                return [500, 'text/plain', 'get url failed']
            # 302 跳转到真实地址
            return [302, 'text/plain', '', {'Location': url}]
        return [404, 'text/plain', 'not found']

    def destroy(self):
        log("Spider 销毁")
        self._cache.clear()
        return


# ========== 兼容不同 TVBox 版本的加载方式 ==========
_spider_instance = None
def get_spider():
    global _spider_instance
    if _spider_instance is None:
        _spider_instance = Spider()
    return _spider_instance


# 有些 TVBox 会直接从这个模块里找名字叫 Spider 的类，不用额外导出
# 有些会调用 main()，这里给出兼容
def main():
    return get_spider()
