"""Liest nur den JSON-Header einer safetensors-Datei, führt nichts aus."""
import json
import struct
import sys

with open(sys.argv[1], "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    print(json.dumps(json.loads(f.read(n))))
