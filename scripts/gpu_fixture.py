"""Small real CUDA task with a TERM-resistant child; QA only."""

import ctypes
import subprocess
import sys
import time

cuda = ctypes.CDLL("libcuda.so.1")
assert cuda.cuInit(0) == 0
device = ctypes.c_int()
assert cuda.cuDeviceGet(ctypes.byref(device), 0) == 0
context = ctypes.c_void_p()
assert cuda.cuCtxCreate_v2(ctypes.byref(context), 0, device) == 0
memory = ctypes.c_uint64()
assert cuda.cuMemAlloc_v2(ctypes.byref(memory), 16 * 1024 * 1024) == 0
child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(90)",
    ]
)
try:
    time.sleep(90)
finally:
    child.kill()
    child.wait()
