import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
import hashlib

DB = "wms.db"

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def get_conn():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS skus (sku_code TEXT PRIMARY KEY, name TEXT, uom TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS inventory (sku_code TEXT PRIMARY KEY, qty REAL DEFAULT 0)")
    conn.execute("""CREATE TABLE IF NOT EXISTS ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, type TEXT, sku_code TEXT, qty REAL, uom TEXT,
        inspection_note TEXT, transfer_note TEXT, mfd TEXT,
        receiving_date TEXT, release_date TEXT, user TEXT, note TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT)""")
    # 加新欄
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(ledger)").fetchall()]
        if "user" not in cols: conn.execute("ALTER TABLE ledger ADD COLUMN user TEXT")
        if "transfer_note" not in cols: conn.execute("ALTER TABLE ledger ADD COLUMN transfer_note TEXT")
    except: pass
    # 預設admin帳號
    if not conn.execute("SELECT * FROM users").fetchone():
        conn.execute("INSERT INTO users VALUES (?,?,?)", ("admin", hash_pw("admin123"), "Admin"))
        conn.commit()
    return conn

conn = get_conn()
st.set_page_config(page_title="WMS 多人版", layout="wide", initial_sidebar_state="collapsed")

# --- LOGIN ---
if "logged_in" not in st.session_state: st.session_state.logged_in=False

if not st.session_state.logged_in:
    st.title("🔐 WMS 登入")
    st.info("預設帳號: admin / 密碼: admin123 (第一次用)")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("登入", type="primary"):
        row = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (u, hash_pw(p))).fetchone()
        if row:
            st.session_state.logged_in=True
            st.session_state.user=u
            st.session_state.role=row[2]
            st.rerun()
        else: st.error("帳號或密碼錯")
    st.stop()

# --- 已登入 ---
st.sidebar.write(f"👤 {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("登出"):
    st.session_state.logged_in=False
    st.rerun()

func_list = ["庫存總覽", "1. 入庫收貨", "2. 出庫發貨", "庫存流水"]
if st.session_state.role=="Admin":
    func_list.append("用戶管理")
    func_list.append("SKU管理")

func = st.sidebar.selectbox("功能", func_list)

# 下面你原有功能保留，只係加咗 user 記錄
def normalize_columns(df):
    col_map={}
    for c in df.columns:
        lc=str(c).lower().strip()
        if "receiving" in lc: col_map[c]="receiving_date"
        elif "release" in lc: col_map[c]="release_date"
        elif "inspection" in lc: col_map[c]="inspection_note"
        elif "transfer" in lc: col_map[c]="transfer_note"
        elif "mfd" in lc: col_map[c]="mfd"
        elif lc=="sku": col_map[c]="sku_code"
        elif lc=="qty": col_map[c]="qty"
        elif "uom" in lc: col_map[c]="uom"
    return df.rename(columns=col_map)

if func=="用戶管理" and st.session_state.role=="Admin":
    st.title("👥 用戶管理 (Admin先見到)")
    st.dataframe(pd.read_sql("SELECT username, role FROM users", conn), use_container_width=True)
    c1,c2,c3 = st.columns(3)
    with c1: new_u=st.text_input("新帳號")
    with c2: new_p=st.text_input("新密碼")
    with c3: new_r=st.selectbox("權限", ["Staff","Admin"])
    if st.button("新增用戶"):
        try:
            conn.execute("INSERT INTO users VALUES (?,?,?)", (new_u, hash_pw(new_p), new_r))
            conn.commit(); st.success(f"已新增 {new_u}")
        except: st.error("帳號已存在")
    st.divider()
    del_u=st.selectbox("刪除用戶", [r[0] for r in conn.execute("SELECT username FROM users").fetchall() if r[0]!="admin"])
    if st.button("刪除"): conn.execute("DELETE FROM users WHERE username=?", (del_u,)); conn.commit(); st.success("已刪除")

elif func=="庫存總覽":
    st.title("庫存總覽")
    df=pd.read_sql("SELECT s.sku_code, s.name, IFNULL(i.qty,0) as qty, s.uom FROM skus s LEFT JOIN inventory i ON s.sku_code=i.sku_code", conn)
    st.dataframe(df, use_container_width=True)

elif func=="1. 入庫收貨":
    st.title("1. 入庫收貨")
    tab1,tab2=st.tabs(["逐筆","批量"])
    with tab1:
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.text_input("Receiving Date", value=now_str, disabled=True)
        col1,col2=st.columns(2)
        with col1:
            inspection_note=st.text_input("Inspection Note # *必填")
            mfd_date=st.date_input("MFD *必填", value=date.today(), format="DD/MM/YYYY")
            mfd_str=mfd_date.strftime("%d/%m/%Y")
        with col2:
            uom=st.selectbox("UOM *必填", ["","PCS","KG"])
            qty=st.number_input("QTY *必填", min_value=0.0, step=1.0)
        skus=pd.read_sql("SELECT sku_code, name FROM skus", conn)
        sku=st.selectbox("SKU *必填", [""]+list(skus["sku_code"]+" - "+skus["name"])) if not skus.empty else ""
        sku_code=sku.split(" - ")[0] if sku else ""
        if st.button("✅ 確認收貨", type="primary"):
            if not all([inspection_note.strip(), uom, qty>0, sku_code]): st.error("仲有必填未填")
            else:
                conn.execute("UPDATE inventory SET qty=qty+? WHERE sku_code=?", (qty, sku_code))
                conn.execute("INSERT INTO ledger (time,type,sku_code,qty,uom,inspection_note,mfd,receiving_date,user) VALUES (?,?,?,?,?,?,?,?,?)",
                             (now_str,"IN",sku_code,qty,uom,inspection_note.strip(),mfd_str,now_str,st.session_state.user))
                conn.commit(); st.success(f"收貨成功 {sku_code} +{qty}"); st.balloons()
    with tab2:
        up=st.file_uploader("上傳Inbound Excel", type=["xlsx","csv"], key="up_in")
        if up:
            df=pd.read_excel(up, sheet_name="Inbound") if "Inbound" in pd.ExcelFile(up).sheet_names else pd.read_excel(up)
            df=normalize_columns(df)
            st.dataframe(df.head(10))
            if st.button("🚀 開始批量入庫"):
                cur=conn.cursor()
                for _,r in df.iterrows():
                    sc=str(r.get("sku_code","")).strip()
                    if not sc: continue
                    q=float(r.get("qty",0)); mfd_v=str(r.get("mfd",""))
                    cur.execute("INSERT OR IGNORE INTO inventory (sku_code,qty) VALUES (?,0)", (sc,))
                    cur.execute("UPDATE inventory SET qty=qty+? WHERE sku_code=?", (q, sc))
                    cur.execute("INSERT INTO ledger (time,type,sku_code,qty,uom,inspection_note,mfd,receiving_date,user) VALUES (?,?,?,?,?,?,?,?,?)",
                                (str(r.get("receiving_date", datetime.now())),"IN",sc,q,str(r.get("uom","PCS")),str(r.get("inspection_note","")),mfd_v,str(r.get("receiving_date", datetime.now())),st.session_state.user))
                conn.commit(); st.success(f"批量完成 {len(df)} 行")

elif func=="2. 出庫發貨":
    st.title("2. 出庫發貨")
    tab1,tab2=st.tabs(["逐筆","批量"])
    with tab1:
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.text_input("Release Date", value=now_str, disabled=True)
        col1,col2=st.columns(2)
        with col1:
            transfer_note=st.text_input("Transfer Note # *必填")
            mfd_date=st.date_input("MFD *必填", value=date.today(), format="DD/MM/YYYY", key="out_mfd")
            mfd_str=mfd_date.strftime("%d/%m/%Y")
        with col2:
            uom=st.selectbox("UOM *必填", ["","PCS","KG"], key="out_uom")
            qty=st.number_input("QTY *必填", min_value=0.0, step=1.0, key="out_qty")
        skus=pd.read_sql("SELECT sku_code, name FROM skus", conn)
        sku=st.selectbox("SKU *必填", [""]+list(skus["sku_code"]+" - "+skus["name"]), key="sku_out") if not skus.empty else ""
        sku_code=sku.split(" - ")[0] if sku else ""
        if st.button("✅ 確認發貨", type="primary"):
            if not all([transfer_note.strip(), uom, qty>0, sku_code]): st.error("仲有必填未填")
            else:
                conn.execute("UPDATE inventory SET qty=qty-? WHERE sku_code=?", (qty, sku_code))
                conn.execute("INSERT INTO ledger (time,type,sku_code,qty,uom,transfer_note,mfd,release_date,user) VALUES (?,?,?,?,?,?,?,?,?)",
                             (now_str,"OUT",sku_code,qty,uom,transfer_note.strip(),mfd_str,now_str,st.session_state.user))
                conn.commit(); st.success(f"發貨成功 {sku_code} -{qty}"); st.balloons()
    with tab2:
        up=st.file_uploader("上傳Outbound Excel", type=["xlsx","csv"], key="up_out")
        if up:
            df=pd.read_excel(up, sheet_name="Outbound") if "Outbound" in pd.ExcelFile(up).sheet_names else pd.read_excel(up)
            df=normalize_columns(df); st.dataframe(df.head(10))
            if st.button("🚀 開始批量出庫"):
                cur=conn.cursor()
                for _,r in df.iterrows():
                    sc=str(r.get("sku_code","")).strip()
                    if not sc: continue
                    q=float(r.get("qty",0))
                    cur.execute("UPDATE inventory SET qty=qty-? WHERE sku_code=?", (q, sc))
                    cur.execute("INSERT INTO ledger (time,type,sku_code,qty,uom,transfer_note,mfd,release_date,user) VALUES (?,?,?,?,?,?,?,?,?)",
                                (str(r.get("release_date", datetime.now())),"OUT",sc,q,str(r.get("uom","PCS")),str(r.get("transfer_note","")),str(r.get("mfd","")),str(r.get("release_date", datetime.now())),st.session_state.user))
                conn.commit(); st.success(f"批量完成 {len(df)} 行")

elif func=="庫存流水":
    st.title("庫存流水")
    t1,t2,t3=st.tabs(["全部","入庫","出庫"])
    df_all=pd.read_sql("SELECT time,type,sku_code,qty,uom,inspection_note,transfer_note,mfd,user FROM ledger ORDER BY id DESC", conn)
    with t1: st.dataframe(df_all, use_container_width=True)
    with t2: st.dataframe(df_all[df_all["type"]=="IN"], use_container_width=True)
    with t3: st.dataframe(df_all[df_all["type"]=="OUT"], use_container_width=True)

elif func=="SKU管理":
    st.title("SKU管理")
    up=st.file_uploader("上傳Master Excel", type=["xlsx","csv"])
    if up:
        df=pd.read_excel(up, sheet_name="Master") if "Master" in pd.ExcelFile(up).sheet_names else pd.read_excel(up)
        if st.button("✅ 確認導入"):
            cur=conn.cursor()
            for _,r in df.iterrows():
                sc=str(r.iloc[0]).strip()
                cur.execute("INSERT OR REPLACE INTO skus (sku_code,name) VALUES (?,?)", (sc, str(r.iloc[1]) if len(r)>1 else sc))
                cur.execute("INSERT OR IGNORE INTO inventory (sku_code,qty) VALUES (?,0)", (sc,))
            conn.commit(); st.success("導入完成")
    st.dataframe(pd.read_sql("SELECT * FROM skus", conn), use_container_width=True)