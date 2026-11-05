import os, sqlite3, shutil, tempfile, datetime
BASE = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default")
def dt(t):
    return (datetime.datetime(1601,1,1)+datetime.timedelta(microseconds=t))
tmp = os.path.join(tempfile.gettempdir(),"h_sep.db")
shutil.copy2(os.path.join(BASE,"History"), tmp)
con = sqlite3.connect(tmp); cur = con.cursor()
lo = int((datetime.datetime(2026,8,20)-datetime.datetime(1601,1,1)).total_seconds()*1e6)
hi = int((datetime.datetime(2026,11,5)-datetime.datetime(1601,1,1)).total_seconds()*1e6)
cur.execute("""SELECT url, COALESCE(title,''), visit_count, last_visit_time FROM urls
               WHERE last_visit_time BETWEEN ? AND ?
                 AND (url LIKE '%aliyun%' OR url LIKE '%tencent%' OR url LIKE '%ecs%'
                      OR url LIKE '%lighthouse%' OR url LIKE '%cvm%' OR url LIKE '%buy%')
               ORDER BY last_visit_time ASC""", (lo,hi))
rows = cur.fetchall()
print(f"=== 8/20 - 11/5 云相关访问 {len(rows)} 条 ===")
for u,t,v,ts in rows:
    d = dt(ts).strftime("%m-%d %H:%M")
    if "buy" in u or "ecs.console" in u or "lighthouse" in u or "cvm" in u:
        print(f"{d} | {v}次 | {u[:160]}")
