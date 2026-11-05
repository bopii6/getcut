import os, sqlite3, shutil, tempfile, datetime

BASE = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default")

def chrome_to_dt(t):
    if not t:
        return "-"
    try:
        return (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=t)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"

# 1) 完整 URL（近两个月，云控制台相关）
tmp = os.path.join(tempfile.gettempdir(), "h_full.db")
shutil.copy2(os.path.join(BASE, "History"), tmp)
con = sqlite3.connect(tmp)
cur = con.cursor()
cur.execute("""SELECT url, COALESCE(title,''), visit_count, last_visit_time FROM urls
               WHERE (url LIKE '%aliyun%' OR url LIKE '%tencent%' OR url LIKE '%volcengine%')
               ORDER BY last_visit_time DESC LIMIT 60""")
print("========== 云控制台 URL 明细（近） ==========")
for url, title, vc, t in cur.fetchall():
    print(f"{chrome_to_dt(t)} | {vc}次 | {url[:150]}")
con.close()

# 2) 保存的账号（只看用户名，不看密码）
print("\n========== 保存的云账号 ==========")
tmp2 = os.path.join(tempfile.gettempdir(), "h_login.db")
try:
    shutil.copy2(os.path.join(BASE, "Login Data"), tmp2)
    con2 = sqlite3.connect(tmp2)
    c2 = con2.cursor()
    c2.execute("""SELECT origin_url, username_value, date_last_used FROM logins
                  WHERE origin_url LIKE '%aliyun%' OR origin_url LIKE '%alibaba%'
                     OR origin_url LIKE '%tencent%' OR origin_url LIKE '%qcloud%'
                     OR origin_url LIKE '%volcengine%'
                  ORDER BY date_last_used DESC""")
    for o, u, d in c2.fetchall():
        print(f"{chrome_to_dt(d)} | {u} | {o[:70]}")
    con2.close()
except Exception as e:
    print("登录库读取失败:", e)
