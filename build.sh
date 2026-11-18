#!/bin/bash
# Builds the two downloads, each with its own Python (python-build-standalone):
#   dist/UDPFS-Server-windows.zip   UDPFS Server.exe + app\ + python\
#   dist/UDPFS-Server-mac.zip       UDPFS Server.app (Intel + Apple silicon)
# Needs bash, curl, tar, zip, unzip. The Windows launcher is rebuilt when
# x86_64-w64-mingw32-gcc is installed (brew install mingw-w64 / apt install
# gcc-mingw-w64-x86-64); otherwise windows/UDPFS Server.exe is used as is.
# The Mac launchers (macos/launcher.c) are rebuilt when zig and lipo
# (llvm-lipo) are installed, otherwise the ones in the templates are used.
# The Mac apps are signed (ad hoc) with codesign on a Mac, or rcodesign
# (cargo install apple-codesign) elsewhere: macOS only asks for Local
# Network permission for a signed app.
set -e
cd "$(dirname "$0")"
PBS_TAG=20261021
PY_VER=3.12.15
BASE="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG"
CACHE=.cache; mkdir -p "$CACHE"
rm -rf dist build && mkdir -p dist build

fetch() { # target triple -> cached tarball path
  local f="cpython-$PY_VER+$PBS_TAG-$1-install_only_stripped.tar.gz"
  [ -s "$CACHE/$f" ] || curl -fL --retry 3 -o "$CACHE/$f" "$BASE/${f//+/%2B}"
  echo "$CACHE/$f"
}
prune() { # python root, stdlib dir: drop what the window never uses
  rm -rf "$2"/test "$2"/idlelib "$2"/ensurepip "$2"/turtledemo "$2"/lib2to3 "$2"/tkinter/test \
         "$2"/site-packages/pip* "$1"/include "$1"/share "$1"/libs "$1"/Scripts
  rm -f "$1"/bin/pip* "$1"/bin/idle* "$1"/bin/pydoc* "$1"/bin/2to3*
  find "$1" -name __pycache__ -type d -prune -exec rm -rf {} +
}
APPFILES=(udpfs_server.py compressed_iso LICENSE.txt udpfs_gui.pyw opl_library.pyw zso_tool.py game_info.py icon.png)
LZ4=4.4.5
wheel() { # platform tag, site-packages dir: lz4 for ZSO (vendor/wheels, from PyPI)
  local w=(vendor/wheels/lz4-$LZ4-cp312-cp312-$1.whl)
  [ -f "${w[0]}" ] || { echo "missing ${w[0]}"; exit 1; }
  mkdir -p "$2" && (cd "$2" && unzip -qo "$OLDPWD/${w[0]}")
}

# ---- Windows
if command -v x86_64-w64-mingw32-gcc >/dev/null; then
  x86_64-w64-mingw32-windres windows/res.rc -O coff -o build/res.o
  x86_64-w64-mingw32-gcc -O2 -municode -mwindows -s -Wl,--no-insert-timestamp -o "windows/UDPFS Server.exe" windows/launcher.c build/res.o
  x86_64-w64-mingw32-windres windows/res_library.rc -O coff -o build/res_library.o
  x86_64-w64-mingw32-gcc -O2 -municode -mwindows -s -Wl,--no-insert-timestamp '-DSCRIPT=L"opl_library.pyw"' \
    '-DAPPNAME=L"OPL Library"' -o "windows/OPL Library.exe" windows/launcher.c build/res_library.o
fi
W="build/win/UDPFS Server"; mkdir -p "$W/app"
tar xzf "$(fetch x86_64-pc-windows-msvc)" -C "$W"
prune "$W/python" "$W/python/Lib"
wheel win_amd64 "$W/python/Lib/site-packages"
cp -R "${APPFILES[@]}" "$W/app/"
cp "windows/UDPFS Server.exe" "windows/OPL Library.exe" windows/README.txt "$W/"
(cd build/win && zip -qr ../../dist/UDPFS-Server-windows.zip "UDPFS Server" -x '*.DS_Store')

# ---- Mac
ZIG=""; command -v zig >/dev/null && ZIG=zig
[ -z "$ZIG" ] && python3 -m ziglang version >/dev/null 2>&1 && ZIG="python3 -m ziglang"
LIPO=$(command -v lipo || command -v llvm-lipo || ls /usr/bin/llvm-lipo-* 2>/dev/null | head -1)
if [ -n "$ZIG" ] && [ -n "$LIPO" ]; then
  mac_launcher() { # name, extra flags...
    local n=$1; shift
    $ZIG cc -target aarch64-macos.11.0 -O2 -Wl,-headerpad_max_install_names "$@" -o build/$n-arm64 macos/launcher.c
    $ZIG cc -target x86_64-macos.10.15 -O2 -Wl,-headerpad_max_install_names "$@" -o build/$n-x86_64 macos/launcher.c
    "$LIPO" -create build/$n-arm64 build/$n-x86_64 -output build/$n
  }
  mac_launcher srv
  mac_launcher lib '-DSCRIPT="opl_library.pyw"' -DFIND_SERVER
  cp build/srv "macos/app-template/Contents/MacOS/UDPFS Server"
  cp build/lib "macos/library-template/Contents/MacOS/OPL Library"
fi
APP="build/mac/UDPFS Server.app"; mkdir -p build/mac
cp -R macos/app-template "$APP"
mkdir -p "$APP/Contents/Resources/app"
for arch in x86_64 aarch64; do
  mkdir -p "$APP/Contents/Resources/python-$arch"
  tar xzf "$(fetch $arch-apple-darwin)" -C "$APP/Contents/Resources/python-$arch" --strip-components=1
  prune "$APP/Contents/Resources/python-$arch" "$APP/Contents/Resources/python-$arch/lib/python3.12"
  if [ $arch = x86_64 ]; then tag=macosx_10_13_x86_64; else tag=macosx_11_0_arm64; fi
  wheel $tag "$APP/Contents/Resources/python-$arch/lib/python3.12/site-packages"
done
cp -R "${APPFILES[@]}" "$APP/Contents/Resources/app/"
chmod +x "$APP/Contents/MacOS/UDPFS Server"
LIBAPP="build/mac/OPL Library.app"
cp -R macos/library-template "$LIBAPP"
chmod +x "$LIBAPP/Contents/MacOS/OPL Library"
cp "macos/READ ME.txt" build/mac/
find build/mac -name __pycache__ -type d -prune -exec rm -rf {} +
for a in "$APP" "$LIBAPP"; do
  if command -v codesign >/dev/null; then
    codesign --force --deep --sign - "$a"
  elif command -v rcodesign >/dev/null; then
    rcodesign sign "$a" >build/sign.log 2>&1 || { tail -5 build/sign.log; exit 1; }
  else
    echo "warning: $a not signed (no codesign or rcodesign): Local Network permission will not work"
  fi
done
(cd build/mac && zip -qry ../../dist/UDPFS-Server-mac.zip "UDPFS Server.app" "OPL Library.app" "READ ME.txt" -x '*.DS_Store')

rm -rf build
ls -l dist
