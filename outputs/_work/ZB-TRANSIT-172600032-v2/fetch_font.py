"""Acquire a font subset for displaying the local Chinese form in Chromium."""
import re
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
root = HERE.parents[2]
page = root / "outputs" / f"authoring_{HERE.name}" / "author_record.html"
characters = "".join(sorted(set(re.findall(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]", page.read_text()))))
params = urllib.parse.urlencode({"family": "Noto Sans SC", "text": characters})
ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
css = urllib.request.urlopen(urllib.request.Request("https://fonts.googleapis.com/css2?" + params, headers={"User-Agent": ua}), timeout=20).read().decode()
url = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+)", css).group(1)
font = urllib.request.urlopen(url, timeout=20).read()
assert font[:4] == b"wOF2"
license_text = urllib.request.urlopen("https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt", timeout=20).read()
assert b"SIL OPEN FONT LICENSE" in license_text
(HERE / "cjk_subset.woff2").write_bytes(font)
(HERE / "font_license.txt").write_bytes(license_text)
print(len(characters),len(font))
