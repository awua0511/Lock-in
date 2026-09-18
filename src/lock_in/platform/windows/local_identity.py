"""Current-user identity and single-instance helpers for Windows."""

from __future__ import annotations

import ctypes
import hashlib
import os

if os.name == "nt":
    from ctypes import wintypes


TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1
ERROR_ALREADY_EXISTS = 183


def current_user_sid() -> str:
    if os.name != "nt":
        raise OSError("Windows user identity is only available on Windows")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("User", SidAndAttributes)]

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    sid_string = wintypes.LPWSTR()
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, TOKEN_USER_CLASS, None, 0, ctypes.byref(required)
        )
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_USER_CLASS,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        if not advapi32.ConvertSidToStringSidW(
            token_user.User.Sid, ctypes.byref(sid_string)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return sid_string.value
    finally:
        if sid_string:
            kernel32.LocalFree(sid_string)
        kernel32.CloseHandle(token)


def user_scope_hash(namespace: str = "default") -> str:
    material = f"{current_user_sid()}\0{namespace}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def pipe_address(namespace: str = "default") -> str:
    return rf"\\.\pipe\LockIn.{user_scope_hash(namespace)}.experiment3.v1"


def mutex_name(namespace: str = "default") -> str:
    return rf"Local\LockIn.{user_scope_hash(namespace)}.experiment3.v1"


class SingleInstanceMutex:
    def __init__(self, name: str) -> None:
        if os.name != "nt":
            raise OSError("Windows mutexes are only available on Windows")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._handle = self._kernel32.CreateMutexW(None, False, name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.already_exists = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> SingleInstanceMutex:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
