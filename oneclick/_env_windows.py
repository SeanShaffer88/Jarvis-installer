"""Private local-NTFS settings store. No native calls occur at import time.

Ancestors must be trusted and stable. Held directory handles reject observed
reparse points and prevent ordinary deletion, not every ancestor-substitution
attack. DACLs cannot protect against privileged or same-user compromise.
"""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import sys
from pathlib import Path
import uuid


P = C.c_void_p
D = W.DWORD
H = W.HANDLE
FILE_ALL_ACCESS = 0x001F01FF
READ_CONTROL = 0x20000
WRITE_DAC = 0x40000
DELETE = 0x10000
REPARSE = 0x400
DIRECTORY = 0x10


class _FileInfo(C.Structure):
    _fields_ = [("attributes", D), ("creation", W.FILETIME),
                ("access", W.FILETIME), ("write", W.FILETIME),
                ("volume", D), ("size_high", D), ("size_low", D),
                ("links", D), ("index_high", D), ("index_low", D)]


class _Acl(C.Structure):
    _fields_ = [("revision", W.BYTE), ("reserved", W.BYTE),
                ("size", W.WORD), ("count", W.WORD), ("reserved2", W.WORD)]


class _Ace(C.Structure):
    _fields_ = [("type", W.BYTE), ("flags", W.BYTE), ("size", W.WORD),
                ("mask", D), ("sid_start", D)]


class _Rename(C.Structure):
    # The SDK union BOOLEAN ReplaceIfExists / DWORD Flags occupies four bytes.
    _fields_ = [("replace", D), ("root", H), ("length", D), ("name", W.WCHAR * 1)]


class NativeError(OSError):
    def __init__(self, stage, code=0):
        super().__init__(code, "Secure settings operation failed")
        self.stage = stage


class _Native:
    def __init__(self):
        if os.name != "nt":
            raise NativeError("platform")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.a = C.WinDLL("advapi32", use_last_error=True)
        declarations = [
            (self.k, "GetCurrentProcess", H, []),
            (self.k, "GetCurrentThread", H, []),
            (self.k, "CloseHandle", W.BOOL, [H]),
            (self.k, "LocalFree", P, [P]),
            (self.k, "CreateFileW", H, [W.LPCWSTR, D, D, P, D, D, H]),
            (self.k, "GetFileInformationByHandle", W.BOOL, [H, C.POINTER(_FileInfo)]),
            (self.k, "GetFileType", D, [H]),
            (self.k, "GetVolumeInformationByHandleW", W.BOOL,
             [H, W.LPWSTR, D, C.POINTER(D), C.POINTER(D), C.POINTER(D), W.LPWSTR, D]),
            (self.k, "GetFinalPathNameByHandleW", D, [H, W.LPWSTR, D, D]),
            (self.k, "GetDriveTypeW", W.UINT, [W.LPCWSTR]),
            (self.k, "ReadFile", W.BOOL, [H, P, D, C.POINTER(D), P]),
            (self.k, "WriteFile", W.BOOL, [H, P, D, C.POINTER(D), P]),
            (self.k, "FlushFileBuffers", W.BOOL, [H]),
            (self.k, "SetFileInformationByHandle", W.BOOL, [H, C.c_int, P, D]),
            (self.a, "OpenThreadToken", W.BOOL, [H, D, W.BOOL, C.POINTER(H)]),
            (self.a, "OpenProcessToken", W.BOOL, [H, D, C.POINTER(H)]),
            (self.a, "GetTokenInformation", W.BOOL, [H, C.c_int, P, D, C.POINTER(D)]),
            (self.a, "IsValidSid", W.BOOL, [P]),
            (self.a, "GetLengthSid", D, [P]),
            (self.a, "CopySid", W.BOOL, [D, P, P]),
            (self.a, "EqualSid", W.BOOL, [P, P]),
            (self.a, "InitializeAcl", W.BOOL, [P, D, D]),
            (self.a, "AddAccessAllowedAceEx", W.BOOL, [P, D, D, D, P]),
            (self.a, "SetSecurityInfo", D, [H, C.c_int, D, P, P, P, P]),
            (self.a, "GetSecurityInfo", D,
             [H, C.c_int, D, C.POINTER(P), C.POINTER(P), C.POINTER(P), C.POINTER(P), C.POINTER(P)]),
            (self.a, "IsValidSecurityDescriptor", W.BOOL, [P]),
            (self.a, "GetSecurityDescriptorControl", W.BOOL, [P, C.POINTER(W.WORD), C.POINTER(D)]),
            (self.a, "GetSecurityDescriptorDacl", W.BOOL,
             [P, C.POINTER(W.BOOL), C.POINTER(P), C.POINTER(W.BOOL)]),
            (self.a, "IsValidAcl", W.BOOL, [P]),
            (self.a, "GetAce", W.BOOL, [P, D, C.POINTER(P)]),
        ]
        for dll, name, result, args in declarations:
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = result, args
        pointer = C.sizeof(P)
        if (C.sizeof(D) != 4 or C.sizeof(W.WCHAR) != 2 or C.sizeof(_FileInfo) != 52
                or C.sizeof(_Acl) != 8 or _Ace.sid_start.offset != 8
                or _Rename.root.offset != (8 if pointer == 8 else 4)
                or _Rename.name.offset != (20 if pointer == 8 else 12)):
            raise NativeError("abi")
        self.sid = self._user_sid()

    def check(self, result, stage):
        if not result:
            raise NativeError(stage, C.get_last_error())
        return result

    def close(self, handle):
        self.check(self.k.CloseHandle(handle), "close")

    def _user_sid(self):
        token = H()
        if self.a.OpenThreadToken(self.k.GetCurrentThread(), 8, True, C.byref(token)):
            self.close(token)
            raise NativeError("impersonation")
        code = C.get_last_error()
        if code != 1008:  # ERROR_NO_TOKEN is the only accepted absence.
            raise NativeError("thread-token", code)
        self.check(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, C.byref(token)), "process-token")
        try:
            needed = D()
            result = self.a.GetTokenInformation(token, 1, None, 0, C.byref(needed))
            if result or C.get_last_error() != 122 or needed.value < C.sizeof(P):
                raise NativeError("token-size", C.get_last_error())
            data = C.create_string_buffer(needed.value)
            self.check(self.a.GetTokenInformation(token, 1, data, needed, C.byref(needed)), "token-user")
            sid = C.cast(data, C.POINTER(P))[0]
            self.check(self.a.IsValidSid(sid), "user-sid")
            length = self.a.GetLengthSid(sid)
            copied = C.create_string_buffer(length)
            self.check(self.a.CopySid(length, copied, sid), "copy-sid")
            return copied
        finally:
            primary = sys.exception()
            try:
                self.close(token)
            except Exception:
                if primary is None:
                    raise
                primary.cleanup_failed = True

    def open(self, path, access, creation=3, share=0):
        handle = self.k.CreateFileW(str(path), access, share, None, creation,
                                    0x02200000, None)  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        if handle == C.c_void_p(-1).value:
            raise NativeError("open", C.get_last_error())
        return handle

    def info(self, handle, *, directory=False):
        info = _FileInfo()
        self.check(self.k.GetFileInformationByHandle(handle, C.byref(info)), "file-info")
        if (self.k.GetFileType(handle) != 1 or info.attributes & REPARSE
                or bool(info.attributes & DIRECTORY) != directory
                or (not directory and info.links != 1)):
            raise NativeError("file-type")
        return (info.volume, info.index_high, info.index_low)

    def local_ntfs(self, handle):
        fs = C.create_unicode_buffer(32)
        self.check(self.k.GetVolumeInformationByHandleW(handle, None, 0, None,
                   None, None, fs, len(fs)), "volume")
        name = C.create_unicode_buffer(32768)
        length = self.k.GetFinalPathNameByHandleW(handle, name, len(name), 0)
        self.check(length, "final-path")
        final = name.value
        if (length >= len(name) or not final.startswith("\\\\?\\")
                or len(final) < 7 or final[5:7] != ":\\"
                or self.k.GetDriveTypeW(final[4:7]) not in (2, 3)
                or fs.value != "NTFS"):
            raise NativeError("local-ntfs")

    def descriptor(self, handle, *, exact):
        owner, acl, descriptor = P(), P(), P()
        code = self.a.GetSecurityInfo(handle, 1, 5, C.byref(owner), None,
                                      C.byref(acl), None, C.byref(descriptor))
        if code:
            raise NativeError("get-security", code)
        try:
            if (not descriptor or not self.a.IsValidSecurityDescriptor(descriptor)
                    or not owner or not self.a.IsValidSid(owner)
                    or not self.a.EqualSid(owner, self.sid)):
                raise NativeError("owner-descriptor")
            if not exact:
                return
            control, revision = W.WORD(), D()
            self.check(self.a.GetSecurityDescriptorControl(descriptor, C.byref(control), C.byref(revision)), "control")
            present, defaulted, actual = W.BOOL(), W.BOOL(), P()
            self.check(self.a.GetSecurityDescriptorDacl(descriptor, C.byref(present), C.byref(actual), C.byref(defaulted)), "dacl")
            if (not present.value or not actual or actual.value != acl.value
                    or not control.value & 0x1000 or not self.a.IsValidAcl(actual)):
                raise NativeError("protected-dacl")
            header = C.cast(actual, C.POINTER(_Acl)).contents
            if header.revision != 2 or header.count != 1:
                raise NativeError("ace-count")
            ace = P()
            self.check(self.a.GetAce(actual, 0, C.byref(ace)), "get-ace")
            entry = C.cast(ace, C.POINTER(_Ace)).contents
            sid = ace.value + _Ace.sid_start.offset
            if (entry.type != 0 or entry.flags != 0 or entry.mask != FILE_ALL_ACCESS
                    or entry.size != 8 + self.a.GetLengthSid(self.sid)
                    or not self.a.IsValidSid(sid) or not self.a.EqualSid(sid, self.sid)):
                raise NativeError("ace-policy")
        finally:
            if self.k.LocalFree(descriptor):
                primary = sys.exception()
                if primary is None:
                    raise NativeError("local-free", C.get_last_error())
                primary.cleanup_failed = True

    def secure(self, handle):
        self.descriptor(handle, exact=False)  # Refuse foreign ownership before mutation.
        size = C.sizeof(_Acl) + 8 + self.a.GetLengthSid(self.sid)
        acl = C.create_string_buffer(size)
        self.check(self.a.InitializeAcl(acl, size, 2), "initialize-acl")
        self.check(self.a.AddAccessAllowedAceEx(acl, 2, 0, FILE_ALL_ACCESS, self.sid), "add-ace")
        code = self.a.SetSecurityInfo(handle, 1, 0x80000004, None, None, acl, None)
        if code:
            raise NativeError("set-security", code)
        self.descriptor(handle, exact=True)

    def read(self, handle):
        chunks = []
        buffer = C.create_string_buffer(65536)
        count = D()
        while True:
            self.check(self.k.ReadFile(handle, buffer, len(buffer), C.byref(count), None), "read")
            if not count.value:
                return b"".join(chunks).decode("utf-8")
            chunks.append(buffer.raw[:count.value])


class WindowsStore:
    def __init__(self, native=None):
        self.native = native if native is not None else _Native()
        self.transaction = None

    def begin(self, path):
        self.transaction = _Transaction(path, self.native)
        return self.transaction

    def secure_temp(self, path):
        transaction = self.transaction
        if transaction is None or path != transaction.temp_path:
            raise NativeError("callback-identity")
        self.native.secure(transaction.handle)
        transaction.secured = True

    def reuse(self, path):
        transaction = _Transaction(path, self.native, reuse=True)
        primary = None
        try:
            if transaction.existing is None:
                return ""
            self.native.secure(transaction.existing)
            return self.native.read(transaction.existing)
        except Exception as error:
            primary = error
            raise
        finally:
            try:
                transaction.close()
            except Exception:
                if primary is None:
                    raise
                primary.cleanup_failed = True


class _Transaction:
    def __init__(self, path, native, *, reuse=False):
        self.native = native
        self.path = Path(os.path.abspath(path))
        self.handle = None
        self.existing = None
        self.directories = []
        self.committed = False
        self.secured = False
        self.original = None
        try:
            if self.path.drive.startswith("\\\\") or ":" in self.path.name:
                raise NativeError("path")
            for directory in reversed(self.path.parents):
                handle = native.open(directory, 0x80, share=3)
                self.directories.append(handle)
                native.info(handle, directory=True)
            native.local_ntfs(self.directories[-1])
            try:
                self.existing = native.open(self.path, 0x80000000 | READ_CONTROL | (WRITE_DAC if reuse else 0), share=1)
            except NativeError as error:
                if error.errno != 2:
                    raise
            if self.existing is not None:
                native.info(self.existing)
                native.descriptor(self.existing, exact=False)
                if not reuse:
                    self.original = native.read(self.existing)
            if reuse:
                return
            for _ in range(16):
                self.temp_path = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
                try:
                    self.handle = native.open(self.temp_path, 0x40000000 | READ_CONTROL | WRITE_DAC | DELETE, creation=1)
                    break
                except NativeError as error:
                    if error.errno not in (80, 183):
                        raise
            if self.handle is None:
                raise NativeError("collision-limit")
            self.identity = native.info(self.handle)
        except Exception as primary:
            cleanup_failed = False
            try:
                self.abort()
            except Exception:
                cleanup_failed = True
            try:
                self.close()
            except Exception:
                cleanup_failed = True
            from .core import EnvPersistenceError
            raise EnvPersistenceError("begin", primary, cleanup_failed) from None

    def check_identity(self):
        if not self.secured or self.native.info(self.handle) != self.identity:
            raise NativeError("identity")
        self.native.descriptor(self.handle, exact=True)

    def write_all(self, content):
        self.check_identity()
        offset = 0
        while offset < len(content):
            chunk = content[offset:offset + 65536]
            buffer, count = C.create_string_buffer(chunk), D()
            self.native.check(self.native.k.WriteFile(self.handle, buffer, len(chunk), C.byref(count), None), "write")
            if count.value == 0 or count.value > len(chunk):
                raise NativeError("partial-write")
            offset += count.value

    def flush(self):
        self.native.check(self.native.k.FlushFileBuffers(self.handle), "flush")

    def publish(self):
        self.check_identity()
        # The old handle disallows deletion until the last precommit checks finish.
        if self.existing is not None:
            handle, self.existing = self.existing, None
            self.native.close(handle)
        name = str(self.path).encode("utf-16-le")
        size = max(C.sizeof(_Rename), _Rename.name.offset + len(name) + 2)
        buffer = C.create_string_buffer(size)
        info = C.cast(buffer, C.POINTER(_Rename)).contents
        info.replace, info.root, info.length = 1, None, len(name)
        C.memmove(C.addressof(buffer) + _Rename.name.offset, name, len(name))
        self.native.check(self.native.k.SetFileInformationByHandle(self.handle, 3, buffer, size), "rename")
        self.committed = True

    def abort(self):
        if self.handle is not None and not self.committed:
            delete = W.BOOL(True)
            self.native.check(self.native.k.SetFileInformationByHandle(self.handle, 4, C.byref(delete), C.sizeof(delete)), "abort")

    def close(self):
        handles = [self.handle, self.existing, *reversed(self.directories)]
        self.handle = self.existing = None
        self.directories = []
        first = None
        for handle in handles:
            if handle is not None:
                try:
                    self.native.close(handle)
                except Exception as error:
                    if first is None:
                        first = error
        if first is not None:
            raise first
