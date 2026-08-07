import requests
import sqlite3
import os
import random
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "bist_tracker.db")

def get_stocks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code FROM stocks')
    stocks = [row[0] for row in c.fetchall()]
    conn.close()
    return stocks

def fetch_kap_notifications(stock_code, from_date, to_date):
    """
    Fetches real live disclosures for a stock using Google News BIST KAP RSS Feed.
    """
    import bs4
    url = f"https://news.google.com/rss/search?q=KAP+BIST+{stock_code}&hl=tr&gl=TR&ceid=TR:tr"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    real_notifications = []
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = bs4.BeautifulSoup(r.text, 'xml')
            items = soup.find_all('item')[:5] # Get top 5 real items
            for item in items:
                title_text = item.title.text if item.title else f"{stock_code} KAP Bildirimi"
                link_text = item.link.text if item.link else f"https://www.kap.org.tr/tr/sirket-bilgileri/ozet/{stock_code}"
                pub_date = item.pubDate.text if item.pubDate else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Determine category from title
                category = "Diğer"
                if "Faaliyet Raporu" in title_text: category = "Faaliyet Raporu"
                elif "Finansal" in title_text or "Bilanço" in title_text: category = "Finansal Rapor"
                elif "Sözleşme" in title_text or "Sipariş" in title_text or "İhale" in title_text: category = "Yeni Sipariş"
                elif "Sermaye" in title_text or "Bedelsiz" in title_text: category = "Sermaye Artırımı"
                elif "Teşvik" in title_text: category = "Teşvik"
                elif "Yatırım" in title_text or "Capex" in title_text: category = "Duran Varlık Alımı (Capex)"
                
                real_notifications.append({
                    "stock_code": stock_code,
                    "category": category,
                    "title": f"{stock_code} - {title_text}",
                    "publish_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "link": link_text,
                    "raw_text": f"GERÇEK BİLDİRİM: {title_text}. Detaylar ve resmi açıklama KAP kaynaklarında yayınlanmıştır."
                })
    except Exception as e:
        print(f"Error scraping live KAP feed for {stock_code}: {e}")
        
    return real_notifications

def scan_kap_for_all_stocks(days_back=1, progress_callback=None):
    stocks = get_stocks()
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    new_records = 0
    total = len(stocks)
    
    for i, stock in enumerate(stocks):
        if progress_callback:
            progress_callback(stock, (total - i) * 2) # approx 2 seconds remaining per stock
            
        notifs = fetch_kap_notifications(stock, from_date, to_date)
        for notif in notifs:
            try:
                c.execute('''
                    INSERT INTO kap_notifications (
                        stock_code, category, title, publish_date, link, summary, is_read
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (notif['stock_code'], notif['category'], notif['title'], notif['publish_date'], notif['link'], notif['raw_text'], 0))
                new_records += 1
            except sqlite3.IntegrityError:
                # Link is UNIQUE, so it's already there
                pass
                
    conn.commit()
    conn.close()
    return new_records

if __name__ == "__main__":
    count = scan_kap_for_all_stocks(days_back=180) # 6 months
    print(f"Scanned KAP. Added {count} new records to summarize.")
