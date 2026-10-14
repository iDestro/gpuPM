"""Unknown same-UID CPU wrapper starts two independent CUDA jobs."""

import subprocess
import sys
import time

children = [
    subprocess.Popen([sys.executable, "/opt/gpupm-qa/gpu_fixture.py"]) for _ in range(2)
]
try:
    for child in children:
        child.wait()
    time.sleep(90)
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
