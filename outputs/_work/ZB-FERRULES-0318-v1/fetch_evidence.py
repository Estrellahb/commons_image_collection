"""取得来源页与本页所用字体子集，均保存至内部工作目录。"""
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import sys

ROOT = Path(__file__).resolve().parent
PAGE = ROOT.parents[1] / "authoring_ZB-FERRULES-0318-v1" / "author_record.html"
headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"}
characters = "".join(sorted({c for c in PAGE.read_text() if ord(c) > 127}))
params = urlencode({"family": "Noto Sans SC:wght@400..700", "text": characters, "display": "swap"})
css = urlopen(Request("https://fonts.googleapis.com/css2?" + params, headers=headers), timeout=25).read().decode()
font_url, = re.findall(r"url\((https://[^)]+)\)", css)
assert urlsplit(font_url).hostname == "fonts.gstatic.com"
font = urlopen(Request(font_url, headers=headers), timeout=25).read()
assert font[:4] == b"wOF2"
(ROOT / "record_font.woff2").write_bytes(font)
license_text = urlopen("https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt", timeout=25).read().decode()
assert "SIL OPEN FONT LICENSE" in license_text
(ROOT / "record_font_OFL.txt").write_text(license_text)
print("font subset", len(characters), "characters", len(font), "bytes")
if "--font-only" in sys.argv:
    sys.exit(0)
source_url = "https://commons.wikimedia.org/wiki/File:Dornbirn-wire_ferrules-01ASD.jpg"
page = urlopen(Request(source_url, headers=headers), timeout=30).read()
(ROOT / "source_page.html").write_bytes(page)
print("source page", len(page), "bytes")
