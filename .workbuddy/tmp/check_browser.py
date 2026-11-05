import os, sqlite3, shutil, tempfile, datetime, sys

HOMES = [
    ("Chrome-Default", os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\History")),
    ("Chrome-Profile1", os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Profile 1\History")),
    ("Edge-Default", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\History")),
]

KEYS = ["aliyun", "alibaba", "tencent", "qcloud", "volcengine", "volces",
        "huaweicloud", "ucloud", "jdcloud", "baiducloud", "azure"]

def chrome_to_dt(t):
    if not t:
        return "-"
    try:
        return (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=t)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"

for name, path in HOMES:
    if not os.path.exists(path):
        print(f"### {name}: 不存在")
        continue
    tmp = os.path.join(tempfile.gettempdir(), f"h_{name}.db")
    try:
        shutil.copy2(path, tmp)
        con = sqlite3.connect(tmp)
        cur = con.cursor()
        cond = " OR ".join(["url LIKE ?" for _ in KEYS])
        params = [f"%{k}%" for k in KEYS]
        cur.execute(f"""SELECT url, COALESCE(title,''), visit_count, last_visit_time
                        FROM urls WHERE {cond} ORDER BY last_visit_time DESC LIMIT 200""", params)
        rows = cur.fetchall()
        print(f"\n### {name}: 命中 {len(rows)} 条")
        seen = set()
        for url, title, vc, t in rows:
            dom = url.split("/")[2] if "//" in url else url
            key = (dom, title[:40])
            if key in seen:
                continue
            seen.add(key)
            print(f"{chrome_to_dt(t)}  [{vc:>3}次]  {dom[:40]}  |  {title[:60]}")
        con.close()
    except Exception as e:
        print(f"### {name}: 读取失败 {e}")
