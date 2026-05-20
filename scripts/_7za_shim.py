"""Shim that wraps 7za.exe to skip macOS symlinked dylibs during extraction.

electron-builder's winCodeSign-2.6.0.7z archive contains symlinks under
darwin/10.12/lib/*.dylib that point at OpenSSL libraries. On Windows, creating
those symlinks requires admin or Developer Mode. They're only used for macOS
codesigning anyway, so for Windows-only builds we exclude them.

This shim is installed at the path of the original 7za.exe; the real binary
is renamed to 7za-real.exe. It forwards every arg untouched, but appends
-x!darwin/10.12/lib for extraction commands. Exit code 0 if the real tool
returned 0 or 2 (2 == warnings, which would otherwise abort electron-builder).
"""
import os
import subprocess
import sys


def main() -> int:
    here = os.path.dirname(os.path.realpath(sys.argv[0]))
    real = os.path.join(here, "7za-real.exe")

    args = sys.argv[1:]
    # Only patch extraction commands; pass everything else through.
    if args and args[0] == "x":
        args = args + ["-x!darwin/10.12/lib", "-x!darwin/10.12/lib/*"]

    result = subprocess.run([real, *args], stdout=sys.stdout, stderr=sys.stderr)
    # electron-builder treats any non-zero exit as fatal. 7-Zip uses 2 for warnings
    # (e.g. permission denied on a single file we already excluded). Treat as success.
    return 0 if result.returncode in (0, 2) else result.returncode


if __name__ == "__main__":
    sys.exit(main())
