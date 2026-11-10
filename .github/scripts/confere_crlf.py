"""Falha se algum arquivo dado tiver linha terminada só em LF (os .bat precisam de CRLF)."""
import sys

bad = []
for path in sys.argv[1:]:
    data = open(path, "rb").read()
    if not data or data.count(b"\n") != data.count(b"\r\n") or not data.endswith(b"\r\n"):
        bad.append(path)
if bad:
    sys.exit("Sem CRLF: " + ", ".join(bad))
print(f"{len(sys.argv) - 1} arquivo(s) com CRLF.")
