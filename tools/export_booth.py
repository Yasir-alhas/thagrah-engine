# يصدّر ثغرات البوث المعتمدة وكاميراته من قاعدة بيانات المنصة إلى ملفات JSON
# التشغيل من مجلد backend:   python export_booth.py
import sqlite3, json
db = sqlite3.connect("thagrah.db")
get = lambda k: [json.loads(r[0]) for r in db.execute("select data from items where kind=?", (k,))]
vulns = [v for v in get("vuln") if v.get("status") == "معتمدة"]
cams = [{k: c[k] for k in ("name", "x", "y", "angle") if k in c} for c in get("camera")]
json.dump(vulns, open("booth_vulnerabilities.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(cams, open("booth_cameras.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"تم: {len(vulns)} ثغرة معتمدة، {len(cams)} كاميرا")
