"""Drive only the native permission dialog in the isolated Xvfb Chrome fixture."""
import ctypes as c
import sys
import time

x = c.CDLL("libX11.so.6")
x.XOpenDisplay.restype = c.c_void_p
x.XDefaultRootWindow.argtypes = [c.c_void_p]
x.XDefaultRootWindow.restype = c.c_ulong
x.XQueryTree.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_ulong), c.POINTER(c.POINTER(c.c_ulong)), c.POINTER(c.c_uint)]
x.XRaiseWindow.argtypes = [c.c_void_p, c.c_ulong]
x.XFlush.argtypes = [c.c_void_p]
x.XSetInputFocus.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_ulong]
x.XStringToKeysym.argtypes = [c.c_char_p]
x.XStringToKeysym.restype = c.c_ulong
x.XKeysymToKeycode.argtypes = [c.c_void_p, c.c_ulong]
x.XKeysymToKeycode.restype = c.c_uint
x.XFree.argtypes = [c.c_void_p]
x.XCloseDisplay.argtypes = [c.c_void_p]
x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]
x.XInternAtom.restype = c.c_ulong
x.XGetWindowProperty.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_long, c.c_long, c.c_int, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int), c.POINTER(c.c_ulong), c.POINTER(c.c_ulong), c.POINTER(c.c_void_p)]
d = x.XOpenDisplay(None)
if not d:
    raise SystemExit("Consent fixture requires xvfb-run")
root, parent, children, count = c.c_ulong(), c.c_ulong(), c.POINTER(c.c_ulong)(), c.c_uint()
x.XQueryTree(d, x.XDefaultRootWindow(d), c.byref(root), c.byref(parent), c.byref(children), c.byref(count))
for i in range(count.value):
    actual, fmt, length, remaining, data = c.c_ulong(), c.c_int(), c.c_ulong(), c.c_ulong(), c.c_void_p()
    x.XGetWindowProperty(d, children[i], x.XInternAtom(d, b"_NET_WM_NAME", 0), 0, 1024, 0, 0, c.byref(actual), c.byref(fmt), c.byref(length), c.byref(remaining), c.byref(data))
    title = c.string_at(data, length.value).decode(errors="replace") if data.value else ""
    if data.value:
        x.XFree(data)
    if sys.argv[1] in title and not title.startswith("DevTools"):
        x.XRaiseWindow(d, children[i])
        x.XSetInputFocus(d, children[i], 2, 0)
        x.XFlush(d)
        time.sleep(0.2)
        break
else:
    raise SystemExit("Source window not found in the Xvfb fixture")
if len(sys.argv) > 2:
    xt = c.CDLL("libXtst.so.6")
    xt.XTestFakeKeyEvent.argtypes = [c.c_void_p, c.c_uint, c.c_int, c.c_ulong]
    # Chrome initially focuses Deny; Tab selects Allow. No application or platform
    # page is clicked. This helper runs only in the disposable Xvfb display.
    for key in ([b"Tab", b"Return"] if sys.argv[2] == "allow" else [b"Return"]):
        code = x.XKeysymToKeycode(d, x.XStringToKeysym(key))
        xt.XTestFakeKeyEvent(d, code, 1, 0)
        xt.XTestFakeKeyEvent(d, code, 0, 0)
        x.XFlush(d)
        time.sleep(0.25)
x.XFlush(d)
x.XFree(children)
x.XCloseDisplay(d)
