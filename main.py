from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import os
from pydantic import BaseModel
from typing import List, Optional

from database import init_db, DB_PATH
from kap_scraper import scan_kap_for_all_stocks
from llm_analyzer import analyze_unread_notifications
from financial_scraper import update_all_stocks_live
import threading

app = FastAPI(title="BIST KAP Tracker")

# Setup scheduler
scheduler = BackgroundScheduler()

def scheduled_kap_scan():
    print("Running scheduled KAP scan...")
    scan_kap_for_all_stocks(days_back=1)
    analyze_unread_notifications()

# Schedule for 09:30 and 16:00 every day
scheduler.add_job(scheduled_kap_scan, 'cron', hour=9, minute=30)
scheduler.add_job(scheduled_kap_scan, 'cron', hour=16, minute=0)
scheduler.start()

# API Routes
@app.get("/api/stocks")
def get_stocks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code FROM stocks')
    stocks = [row[0] for row in c.fetchall()]
    conn.close()
    return stocks

scan_state = {
    "is_active": False,
    "current_stock": "",
    "remaining_seconds": 0
}

@app.get("/api/kap/status")
def get_kap_status():
    return scan_state

class StockItem(BaseModel):
    code: str

@app.post("/api/stocks")
def add_stock(item: StockItem):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO stocks (code) VALUES (?)', (item.code.upper(),))
        conn.commit()
    except sqlite3.IntegrityError:
        return {"status": "error", "message": "Stock already exists"}
    finally:
        conn.close()
    return {"status": "success"}

@app.delete("/api/stocks/{code}")
def remove_stock(code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM stocks WHERE code = ?', (code.upper(),))
    conn.commit()
    conn.close()
    return {"status": "success"}

from fastapi.responses import HTMLResponse

@app.get("/api/financials/html", response_class=HTMLResponse)
def get_financials_html(metric: str = "roic_vs_wacc"):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM financials")
    data = c.fetchall()
    conn.close()
    
    if not data:
        return "<tr><td class='empty-state' style='padding:2rem;text-align:center;'>Veri bulunamadı veya taranıyor...</td></tr>"
        
    # Restructure data
    # result: { "EGEEN": { "2021Q1": row, "2021Q2": row } }
    result = {}
    quarters_set = set()
    
    for row in data:
        s_code = row['stock_code']
        q = row['quarter']
        if s_code not in result:
            result[s_code] = {}
        result[s_code][q] = dict(row)
        quarters_set.add(q)
        
    quarters = sorted(list(quarters_set))
    stocks_list = sorted(list(result.keys()))
    
    # Generate HTML
    html = "<thead><tr><th>Hisse</th>"
    for q in quarters:
        # Check if future
        # Format: 2024Q3
        is_future = False
        try:
            y = int(q[:4])
            qr = int(q[5:])
            import datetime
            now = datetime.datetime.now()
            curr_q = (now.month - 1) // 3 + 1
            if y > now.year or (y == now.year and qr > curr_q):
                is_future = True
        except:
            pass
            
        future_class = "cell-future" if is_future else ""
        html += f"<th class='{future_class}'>{q}</th>"
        
    html += "</tr></thead><tbody>"
    
    for s_code in stocks_list:
        html += f"<tr><td class='stock-code'>{s_code}</td>"
        for q in quarters:
            row_data = result[s_code].get(q)
            cell_class = ""
            cell_value = "-"
            
            is_future = False
            try:
                y = int(q[:4])
                qr = int(q[5:])
                if y > datetime.datetime.now().year or (y == datetime.datetime.now().year and qr > (datetime.datetime.now().month - 1) // 3 + 1):
                    is_future = True
            except:
                pass
            future_class = "cell-future" if is_future else ""
            
            if row_data:
                if metric == "roic_vs_wacc":
                    diff = row_data['roic'] - row_data['wacc']
                    if diff > 0.05: cell_class = "cell-green"
                    elif diff > 0: cell_class = "cell-yellow"
                    else: cell_class = "cell-red"
                    cell_value = f"{row_data['roic']*100:.1f}%"
                elif metric == "roe":
                    if row_data['roe'] > 0.40: cell_class = "cell-green"
                    elif row_data['roe'] > 0.15: cell_class = "cell-yellow"
                    else: cell_class = "cell-red"
                    cell_value = f"{row_data['roe']*100:.1f}%"
                elif metric == "wacc":
                    cell_class = "cell-yellow"
                    cell_value = f"{row_data['wacc']*100:.1f}%"
                    
            html += f"<td class='{cell_class} {future_class}'>{cell_value}</td>"
        html += "</tr>"
        
    html += "</tbody>"
    return html

@app.get("/api/financials")
def get_financials(stock: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if stock:
        c.execute('SELECT * FROM financials WHERE stock_code = ? ORDER BY quarter ASC', (stock.upper(),))
    else:
        c.execute('SELECT * FROM financials ORDER BY stock_code, quarter ASC')
    data = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # Restructure for heatmap: { "EGEEN": [{"quarter": "2023Q1", "roe": 0.5, ...}, ...], ... }
    result = {}
    for row in data:
        s_code = row['stock_code']
        if s_code not in result:
            result[s_code] = []
        result[s_code].append(row)
        
    return result

@app.get("/api/kap")
def get_kap_notifications(stock: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = 'SELECT * FROM kap_notifications WHERE is_read = 1'
    params = []
    
    if stock:
        query += ' AND stock_code = ?'
        params.append(stock.upper())
        
    query += ' ORDER BY publish_date DESC LIMIT 50'
    
    c.execute(query, tuple(params))
    data = [dict(row) for row in c.fetchall()]
    conn.close()
    return {"notifications": data}

@app.get("/api/kap/html")
def get_kap_notifications_html(
    stock: str = "Tümü", 
    signal: str = "Tümü", 
    minImpact: int = 0, 
    category: str = "Tümü", 
    dateStr: str = ""
):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = 'SELECT * FROM kap_notifications'
    params = []
    c.execute(query, tuple(params))
    data = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # Filter locally
    filtered = []
    for n in data:
        if stock != 'Tümü' and n['stock_code'] != stock: continue
        if signal != 'Tümü' and n['signal'] != signal: continue
        try:
            impact_val = int(n['kap_impact']) if n['kap_impact'] is not None else 0
        except ValueError:
            impact_val = 0
            
        if impact_val < minImpact: continue
        if category != 'Tümü' and n['category'] != category: continue
        if dateStr and not n['publish_date'].startswith(dateStr): continue
        filtered.append(n)
        
    # Sort by publish date desc
    filtered.sort(key=lambda x: x['publish_date'], reverse=True)
    
    total = len(filtered)
    pos = sum(1 for n in filtered if n['signal'] == 'Pozitif')
    neg = sum(1 for n in filtered if n['signal'] == 'Negatif')
    def safe_int(val):
        try:
            return int(val) if val is not None else 0
        except ValueError:
            return 0
            
    high = sum(1 for n in filtered if safe_int(n['kap_impact']) >= 7)
    
    html = ""
    for notif in filtered:
        pub_date_str = notif.get('publish_date', '')
        try:
            from datetime import datetime
            dt = datetime.strptime(pub_date_str.split('.')[0], "%Y-%m-%d %H:%M:%S")
            formatted_date = dt.strftime("%d.%m.%Y - %H:%M")
        except Exception:
            formatted_date = pub_date_str

        if notif.get('is_read') == 0:
            html += f"""
                <div class="kap-card" style="opacity: 0.7;">
                    <div class="kap-card-meta" style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:0.3rem;">
                        <span>{notif['stock_code']} - {notif['category']}</span>
                        <span style="font-size:0.7rem; color:var(--accent); background:rgba(6,182,212,0.1); padding:0.15rem 0.5rem; border-radius:4px; font-weight:600;">🕒 {formatted_date}</span>
                    </div>
                    <div class="kap-card-title" style="margin-top:0.5rem; font-size:1rem; font-weight:700; color:var(--accent);">{notif['title']}</div>
                    <div class="kap-card-summary" style="margin-top:0.5rem; font-size:0.85rem; line-height:1.5; color:var(--text-muted);">
                        <em>[Yapay Zeka API kota sınırına ulaştığı için analiz bekleniyor. Kota sıfırlandığında otomatik taranacaktır.]</em>
                    </div>
                    <div style="margin-top:auto; padding-top:0.8rem; display:flex; justify-content:flex-end;">
                        <a href="{notif['link']}" target="_blank" style="color:var(--accent); text-decoration:none;">Orijinal KAP &rarr;</a>
                    </div>
                </div>
            """
            continue
            
        sigCol = 'var(--neutral)'
        if notif['signal'] == 'Pozitif': sigCol = 'var(--positive)'
        if notif['signal'] == 'Negatif': sigCol = 'var(--negative)'
        
        financial_eff = notif.get('financial_effect', 'Veri yok')
        if not financial_eff: financial_eff = 'Veri yok'
        
        html += f"""
            <div class="kap-card">
                <div class="kap-card-meta" style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:0.3rem;">
                    <span>{notif['stock_code']} - {notif['category']}</span>
                    <span style="font-size:0.7rem; color:var(--accent); background:rgba(6,182,212,0.1); padding:0.15rem 0.5rem; border-radius:4px; font-weight:600;">🕒 {formatted_date}</span>
                </div>
                <div class="kap-card-title" style="margin-top:0.5rem; font-size:1rem; font-weight:700; color:var(--accent);">{notif['title']}</div>
                <div class="kap-card-summary" style="margin-top:0.5rem; font-size:0.85rem; line-height:1.5;">{notif['summary']}</div>
                
                <div style="margin-top:0.8rem; display:flex; flex-direction:column; gap:0.4rem; font-size:0.8rem; background:rgba(0,0,0,0.2); padding:0.8rem; border-radius:6px; border-left:3px solid var(--border-color);">
                    <div style="color:var(--positive)">🟢 <strong>Olumlu Taraf:</strong> {notif['positive_side']}</div>
                    <div style="color:var(--negative)">🔴 <strong>Olumsuz Yön/Risk:</strong> {notif['negative_side']}</div>
                    <div style="color:var(--neutral); border-top:1px dashed rgba(255,255,255,0.1); padding-top:0.4rem; margin-top:0.2rem;">
                        <strong>ROE/ROIC/WACC Etkisi:</strong> {financial_eff}
                    </div>
                </div>
                
                <div style="margin-top:auto; padding-top:0.8rem; display:flex; justify-content:space-between; align-items:center; font-size:0.75rem;">
                    <div style="display:flex; gap:0.5rem;">
                        <span style="background:rgba(255,255,255,0.05); padding:0.2rem 0.5rem; border-radius:4px; font-weight:700; color:{sigCol}">Sinyal: {notif['signal']}</span>
                        <span style="background:rgba(255,255,255,0.05); padding:0.2rem 0.5rem; border-radius:4px; font-weight:700;">KAP Etkisi: {notif['kap_impact']}/10</span>
                    </div>
                    <a href="{notif['link']}" target="_blank" style="color:var(--accent); text-decoration:none;">Detay &rarr;</a>
                </div>
            </div>
        """
        
    return {
        "html": html,
        "stats": {
            "total": total,
            "positive": pos,
            "negative": neg,
            "high": high
        }
    }

@app.post("/api/kap/manual-scan")
def manual_scan(background_tasks: BackgroundTasks):
    def task():
        scan_state["is_active"] = True
        
        def update_status(stock, seconds):
            scan_state["current_stock"] = stock
            scan_state["remaining_seconds"] = seconds
            
        try:
            scan_kap_for_all_stocks(days_back=5, progress_callback=update_status)
            analyze_unread_notifications(progress_callback=update_status)
        finally:
            scan_state["is_active"] = False
            scan_state["current_stock"] = ""
            scan_state["remaining_seconds"] = 0
    
    background_tasks.add_task(task)
    return {"status": "success", "message": "Manual scan started in background."}

# Serve Static files dynamically (works whether files are in root or /static folder)
BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static") if os.path.exists(os.path.join(BASE_DIR, "static")) else BASE_DIR

if os.path.exists(os.path.join(BASE_DIR, "static")):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
else:
    @app.get("/static/{file_path:path}")
    def serve_static_root(file_path: str):
        file_full_path = os.path.join(BASE_DIR, file_path)
        if os.path.exists(file_full_path):
            return FileResponse(file_full_path)
        return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.get("/")
def serve_index():
    idx_path = os.path.join(STATIC_DIR, "index.html") if os.path.exists(os.path.join(STATIC_DIR, "index.html")) else os.path.join(BASE_DIR, "index.html")
    return FileResponse(idx_path)

@app.on_event("startup")
def startup_event():
    init_db()
    
    # Check if we have financials, if not generate mock
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM financials')
    count = c.fetchone()[0]
    conn.close()
    
    if count == 0:
        print("No financial data found. Starting live scraper in background... (This will take ~1 minute)")
        threading.Thread(target=update_all_stocks_live, daemon=True).start()
        
    os.makedirs("static", exist_ok=True)
