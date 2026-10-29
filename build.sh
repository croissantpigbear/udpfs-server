#!/bin/bash
# Builds dist/udpfs-server.zip (Windows/Linux) and dist/UDPFS-Server-mac.zip.
set -e
cd "$(dirname "$0")"
rm -rf dist build && mkdir -p dist build/udpfs-server build/mac
SRV=(udpfs_server.py compressed_iso LICENSE.txt udpfs_gui.pyw)

cp -R "${SRV[@]}" build/udpfs-server/
cp windows-README.txt build/udpfs-server/README.txt
(cd build && zip -qr ../dist/udpfs-server.zip udpfs-server -x '*/__pycache__/*' '*.DS_Store')

APP="build/mac/UDPFS Server.app"
cp -R macos/app-template "$APP"
mkdir -p "$APP/Contents/Resources/udpfs-server"
cp -R "${SRV[@]}" "$APP/Contents/Resources/udpfs-server/"
chmod +x "$APP/Contents/MacOS/UDPFS Server"
cp "macos/READ ME.txt" build/mac/
(cd build/mac && zip -qr ../../dist/UDPFS-Server-mac.zip "UDPFS Server.app" "READ ME.txt" -x '*/__pycache__/*' '*.DS_Store')
rm -rf build
echo "dist/udpfs-server.zip and dist/UDPFS-Server-mac.zip"
