"""Probe: save the raw HTML of OPCOM's intraday report pages (public) so the form/table layout can be inspected.
Writes research/data/opcom_probe/*.html. Manual research only; does not touch the live screen."""
import os, re, urllib.request, urllib.parse, http.cookiejar
OUT = "research/data/opcom_probe"; os.makedirs(OUT, exist_ok=True)
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", "Mozilla/5.0 (research)"), ("Accept-Language", "ro,en")]
pages = {"ida": "https://www.opcom.ro/rapoarte-ida-rezultate-licitatii/ro",
         "pi": "https://www.opcom.ro/rapoarte-pi-rezultate-pi/ro",
         "picup": "https://www.opcom.ro/rapoarte-pi-raport-cuplare-pi/ro",
         "idacup": "https://www.opcom.ro/rapoarte-ida-rezultate-cuplare/ro",
         "pzu": "https://www.opcom.ro/grafice-ip-raportPIP-si-volumTranzactionat/ro"}
for k, u in pages.items():
    try:
        h = op.open(u, timeout=60).read().decode("utf8", "replace")
        open(f"{OUT}/{k}.html", "w").write(h); print(k, len(h))
        forms = re.findall(r"<form.*?</form>", h, re.S)
        open(f"{OUT}/{k}_forms.txt", "w").write("\n\n=====\n\n".join(forms))
    except Exception as e: print(k, "ERR", e)
