import struct

_S1 = bytes.fromhex(
    "a985d6d3541dac255d43181e51fcca632844209de0e2c817a58f037bbb13d2ee708c3fa832ddf674ec950b575c5bbd01241c739810ccf2d92ce772839bd186c96050a3eb0db69e4fb75ac678a612afd561c3b441527d8d081f9900190453f7e1fd762f27b08b0eaba26e934d697c090abfeff3c58714fe64de2e4b1a06216b6602f5928a0cb37ed07a4796e52680addfa13037ae36152238f4a7454c81e9849735cbce3c7111c78975fbdaf8945982c4ff493967c0cfd7b80f8e4223916cdba434f148c26f3d2d40be3ebcc1aaba4e553bdc687f9cd84a5677a0ed46b52b65fae3b9b19f5ef9e6b231ea6d5fe4f0cd88163a58d462290733e81b0579906a2a9a")
_S2 = bytes.fromhex(
    "38e82da6cfdeb3b8af6055c7446f6b5bc36233b529a0e2a7d39111061cbc364bef886ca817c416f4c245e1d63f3d8e98284ef63ea5f90ddfd82b667a272ff17242d441c07367ac8bf7ad801fca2caa34d20beee95d9418f857ae08c513cd86b9ff7dc131f58a6ab1d120d7022204687107db9d9961bee659dd5190dc9aa3abd0810f471ae3ec8dbf967b5ca2a163234dc89e9c3a0c2eba6e9f5af292f34978cc15fb70757f351003646dc674d5b4ea097619fe4012e0bd05fa01f02a5ea956438514899bb0e5487997fc1e82218c1b5f7754b21d254f0046ed5852eb7edac9fd3095653cb6e4bb7c0e5039263284699337e724a4cb530a87d94c838fce3b4ab7")

_KC = (0x9E3779B9, 0x3C6EF373, 0x78DDE6E6, 0xF1BBCDCC, 0xE3779B99, 0xC6EF3733, 0x8DDE6E67, 0x1BBCDCCF,
       0x3779B99E, 0x6EF3733C, 0xDDE6E678, 0xBBCDCCF1, 0x779B99E3, 0xEF3733C6, 0xDE6E678D, 0xBCDCCF1B)
_M = 0xFFFFFFFF


def _ss(box, m):
    return [(box[x] & m[0]) << 24 | (box[x] & m[1]) << 16 | (box[x] & m[2]) << 8 | (box[x] & m[3])
            for x in range(256)]


_SS0 = _ss(_S1, (0x3F, 0xCF, 0xF3, 0xFC))
_SS1 = _ss(_S2, (0xFC, 0x3F, 0xCF, 0xF3))
_SS2 = _ss(_S1, (0xF3, 0xFC, 0x3F, 0xCF))
_SS3 = _ss(_S2, (0xCF, 0xF3, 0xFC, 0x3F))


def _g(x):
    return _SS3[x >> 24 & 255] ^ _SS2[x >> 16 & 255] ^ _SS1[x >> 8 & 255] ^ _SS0[x & 255]


def _round_keys(key):
    k0, k1, k2, k3 = struct.unpack(">4I", key)
    out = []
    for i in range(16):
        out.append((_g((k0 + k2 - _KC[i]) & _M), _g((k1 - k3 + _KC[i]) & _M)))
        if i % 2 == 0:
            k0, k1 = (k0 >> 8 | k1 << 24) & _M, (k1 >> 8 | k0 << 24) & _M
        else:
            k2, k3 = (k2 << 8 | k3 >> 24) & _M, (k3 << 8 | k2 >> 24) & _M
    return out


def _block(rk, data):
    l0, l1, r0, r1 = struct.unpack(">4I", data)
    for k0, k1 in rk:
        t0 = r0 ^ k0
        t1 = _g((r1 ^ k1) ^ t0)
        t0 = _g((t0 + t1) & _M)
        t1 = _g((t1 + t0) & _M)
        t0 = (t0 + t1) & _M
        l0, l1, r0, r1 = r0, r1, l0 ^ t0, l1 ^ t1
    return struct.pack(">4I", r0, r1, l0, l1)


def encrypt_block(key, block):
    return _block(_round_keys(key), block)


def encrypt_cbc(key, iv, data):
    rk = _round_keys(key)
    pad = 16 - len(data) % 16
    data = data + bytes(pad - 1) + bytes([pad])
    out, prev = [], iv
    for i in range(0, len(data), 16):
        prev = _block(rk, bytes(a ^ b for a, b in zip(data[i:i + 16], prev)))
        out.append(prev)
    return b"".join(out)
