"""
This module implements clipboard handling on Windows using ctypes.
"""
import time
import contextlib
import ctypes
from ctypes import c_size_t, sizeof, c_wchar_p, get_errno, c_wchar
from ctypes.wintypes import HGLOBAL, LPVOID, DWORD, LPCSTR, INT, HWND, HINSTANCE, HMENU, BOOL, UINT, HANDLE
from .exceptions import PyperclipWindowsException


class CheckedCall(object):
    def __init__(self, f):
        super(CheckedCall, self).__setattr__("f", f)

    def __call__(self, *args):
        ret = self.f(*args)
        if not ret and get_errno():
            raise PyperclipWindowsException("Error calling " + self.f.__name__)
        return ret

    def __setattr__(self, key, value):
        setattr(self.f, key, value)


def init_windows_clipboard(cygwin=False):
    if cygwin:
        windll = ctypes.cdll  # TODO: This is untested
    else:
        windll = ctypes.windll

    safeCreateWindowExA = CheckedCall(windll.user32.CreateWindowExA)
    safeCreateWindowExA.argtypes = [DWORD, LPCSTR, LPCSTR, DWORD, INT, INT, INT, INT, HWND, HMENU, HINSTANCE, LPVOID]
    safeCreateWindowExA.restype = HWND

    safeDestroyWindow = CheckedCall(windll.user32.DestroyWindow)
    safeDestroyWindow.argtypes = [HWND]
    safeDestroyWindow.restype = BOOL

    OpenClipboard = windll.user32.OpenClipboard
    OpenClipboard.argtypes = [HWND]
    OpenClipboard.restype = BOOL

    safeCloseClipboard = CheckedCall(windll.user32.CloseClipboard)
    safeCloseClipboard.argtypes = []
    safeCloseClipboard.restype = BOOL

    safeEmptyClipboard = CheckedCall(windll.user32.EmptyClipboard)
    safeEmptyClipboard.argtypes = []
    safeEmptyClipboard.restype = BOOL

    safeGetClipboardData = CheckedCall(windll.user32.GetClipboardData)
    safeGetClipboardData.argtypes = [UINT]
    safeGetClipboardData.restype = HANDLE

    safeSetClipboardData = CheckedCall(windll.user32.SetClipboardData)
    safeSetClipboardData.argtypes = [UINT, HANDLE]
    safeSetClipboardData.restype = HANDLE

    safeGlobalAlloc = CheckedCall(windll.kernel32.GlobalAlloc)
    safeGlobalAlloc.argtypes = [UINT, c_size_t]
    safeGlobalAlloc.restype = HGLOBAL

    safeGlobalLock = CheckedCall(windll.kernel32.GlobalLock)
    safeGlobalLock.argtypes = [HGLOBAL]
    safeGlobalLock.restype = LPVOID

    safeGlobalUnlock = CheckedCall(windll.kernel32.GlobalUnlock)
    safeGlobalUnlock.argtypes = [HGLOBAL]
    safeGlobalUnlock.restype = BOOL

    wcscpy_s = ctypes.cdll.msvcrt.wcscpy_s
    wcscpy_s.argtypes = [c_wchar_p, c_size_t, c_wchar_p]
    wcscpy_s.restype = c_wchar_p

    GMEM_MOVEABLE = 0x0002
    CF_UNICODETEXT = 13

    @contextlib.contextmanager
    def window():
        """
        Context that provides a valid Windows hwnd.
        """
        # we really just need the hwnd, so setting "STATIC" as predefined lpClass is just fine.
        hwnd = safeCreateWindowExA(0, b"STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
        try:
            yield hwnd
        finally:
            safeDestroyWindow(hwnd)

    @contextlib.contextmanager
    def clipboard(hwnd):
        """
        Context manager that opens the clipboard and prevents other applications from modifying the clipboard content.
        """
        # We may not get the clipboard handle immediately because some other application is accessing it (?)
        # We try for at least 500ms to get the clipboard.
        t = time.time() + 0.5
        success = False
        while time.time() < t:
            success = OpenClipboard(hwnd)
            if success:
                break
            time.sleep(0.01)
        if not success:
            raise PyperclipWindowsException("Error calling OpenClipboard")

        try:
            yield
        finally:
            safeCloseClipboard()

    def copy_windows(text):
        # This function is heavily based on
        # https://msdn.microsoft.com/de-de/library/windows/desktop/ms649016(v=vs.85).aspx#_win32_Copying_Information_to_the_Clipboard

        with window() as hwnd:
            # https://msdn.microsoft.com/de-de/library/windows/desktop/ms649048(v=vs.85).aspx
            # > If an application calls OpenClipboard with hwnd set to NULL, EmptyClipboard sets the clipboard owner to
            # > NULL; this causes SetClipboardData to fail.
            # => We need a valid hwnd to copy something.
            with clipboard(hwnd):
                safeEmptyClipboard()

                if text:
                    # https://msdn.microsoft.com/de-de/library/windows/desktop/ms649051(v=vs.85).aspx
                    # > If the hMem parameter identifies a memory object, the object must have been allocated using the
                    # > function with the GMEM_MOVEABLE flag.
                    handle = safeGlobalAlloc(GMEM_MOVEABLE, (len(text) + 1) * sizeof(c_wchar))
                    locked_handle = safeGlobalLock(handle)

                    if wcscpy_s(c_wchar_p(locked_handle), len(text) + 1, c_wchar_p(text)):
                        raise PyperclipWindowsException("Error calling wcscpy_s")

                    safeGlobalUnlock(handle)
                    safeSetClipboardData(CF_UNICODETEXT, handle)

    def paste_windows():
        with clipboard(None):
            handle = safeGetClipboardData(CF_UNICODETEXT)
            if not handle:
                # GetClipboardData may return NULL with errno == NO_ERROR if the clipboard is empty.
                # (Also, it may return a handle to an empty buffer, but technically that's not empty)
                return ""
            return c_wchar_p(handle).value

    return copy_windows, paste_windows