"""Erzeugt eine bösartige Pickle-Datei und eine harmlose safetensors-Datei."""
import json
import pickle
import struct


class Evil:
    def __reduce__(self):  # wird beim Laden ausgeführt
        return (print, ("!!! Code beim Laden ausgeführt",))


with open("model.pkl", "wb") as f:
    pickle.dump({"weights": [0.1, 0.2], "x": Evil()}, f)

data = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
header = {"w": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, len(data)]},
          "__metadata__": {"format": "pt"}}
h = json.dumps(header).encode()
with open("model.safetensors", "wb") as f:
    f.write(struct.pack("<Q", len(h)) + h + data)
