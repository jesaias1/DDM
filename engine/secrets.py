"""Windows DPAPI: key material is bound to the current Windows user and machine."""
import base64
import ctypes
import os
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _transform(value, decrypt=False):
    if os.name != "nt":
        raise ValueError("Gem API-noegler som miljoevariabler paa denne platform; DPAPI kraever Windows")
    buffer = ctypes.create_string_buffer(value)
    source = _Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("Windows kunne ikke beskytte/laese noeglerne; brug den oprindelige Windows-konto")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def encrypt(value):
    return base64.b64encode(_transform(value.encode("utf-8"))).decode("ascii")


def decrypt(value):
    try:
        return _transform(base64.b64decode(value, validate=True), True).decode("utf-8")
    except (ValueError, UnicodeError):
        raise ValueError("De gemte noegler kan ikke dekrypteres paa denne Windows-konto") from None
