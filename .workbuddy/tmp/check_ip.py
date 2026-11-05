import os, sqlite3, shutil, tempfile, datetime
BASE = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default")
def dt(t):
    if not t: return "-"
    try:
        return (datetime.datetime(1601,1,1)+datetime.timedelta(microseconds=t)).strftime("%Y-%m-%d %H:%M")
    except: return "-"
tmp = os.path.join(tempfile.gettempdir(),"h_ip.db")
shutil.copy2(os.path.join(BASE,"History"), tmp)
con = sqlite3.connect(tmp); cur = con.cursor()
ips = ["8.140.220.104","47.84.31.168","115.190.113.128","152.136.119.62"]
cond = " OR ".join(["url LIKE ?"]*len(ips))
cur.execute(f"SELECT url, COALESCE(title,''), visit_count, last_visit_time FROM urls WHERE {cond} ORDER BY last_visit_time DESC LIMIT 40",
            [f"%{i}%" for i in ips])
rows = cur.fetchall()
print(f"=== 直连 IP 的访问记录 {len(rows)} 条 ===")
for u,t,v,ts in rows:
    print(f"{dt(ts)} | {v}次 | {u[:120]} | {t[:50]}")
# 搜索词
print("\n=== 云相关搜索词 ===")
try:
    cur.execute("""SELECT k.term, u.last_visit_time FROM keyword_search_terms k
                   JOIN urls u ON u.id=k.url_id ORDER BY u.last_visit_time DESC LIMIT 300""")
    import re
    for term, ts in cur.fetchall():
        if re.search(r"服务器|云|阿里|腾讯|ECS|轻量|4核|4G|主机", term, re.I):
            print(f"{dt(ts)} | {term[:70]}")
except Exception as e:
    print("搜索词读取失败:", e)
con.close()
