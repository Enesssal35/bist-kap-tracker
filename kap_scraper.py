import requests
import sqlite3
import os
import re
import bs4
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "bist_tracker.db")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'tr-TR,tr;q=0.9',
}

WATCHLIST = ['BRSAN', 'PGSUS', 'EGEEN', 'FROTO', 'CCOLA', 'CLEBI', 'OTKAR', 'ISMEN', 'ANSGR', 'LOGO', 'LKMNH', 'ALKA', 'ALTNY', 'SDTTR']

def get_stocks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code FROM stocks')
    stocks = [row[0] for row in c.fetchall()]
    conn.close()
    return stocks or WATCHLIST


def fetch_kap_rss():
    """KAP'ın kendi resmi RSS beslemesinden tüm bildirimleri çeker."""
    url = "https://www.kap.org.tr/tr/rss/bildirimler"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'utf-8'
        soup = bs4.BeautifulSoup(r.text, 'xml')
        return soup.find_all('item')
    except Exception as e:
        print(f"[KAP RSS] Hata: {e}")
        return []


def fetch_google_news_rss(stock_code):
    """Fallback: Google News RSS ile haber çeker."""
    url = f"https://news.google.com/rss/search?q=KAP+%22{stock_code}%22&hl=tr&gl=TR&ceid=TR:tr"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = 'utf-8'
        soup = bs4.BeautifulSoup(r.text, 'xml')
        return soup.find_all('item')[:5]
    except Exception as e:
        print(f"[Google RSS] {stock_code} hata: {e}")
        return []


def categorize(title):
    tl = title.lower()
    if "faaliyet raporu" in tl: return "Faaliyet Raporu"
    if "finansal" in tl or "bilanco" in tl or "bilanço" in tl or "kar" in tl: return "Finansal Rapor"
    if "sozlesme" in tl or "sözleşme" in tl or "siparis" in tl or "ihale" in tl: return "Yeni Sözleşme/Sipariş"
    if "sermaye" in tl or "bedelsiz" in tl: return "Sermaye Artırımı"
    if "temettü" in tl or "temettु" in tl or "kar dagilim" in tl: return "Temettü"
    if "yatirim" in tl or "yatırım" in tl: return "Yatırım"
    if "teşvik" in tl or "tesvik" in tl: return "Teşvik"
    return "Özel Durum Açıklaması"


def scan_kap_for_all_stocks(days_back=1, progress_callback=None):
    stocks = get_stocks()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    new_records = 0

    # --- Önce KAP resmi RSS'ini dene ---
    print("[SCRAPER] KAP resmi RSS deneniyor...")
    kap_items = fetch_kap_rss()
    print(f"[SCRAPER] KAP RSS'den {len(kap_items)} item geldi.")

    if kap_items:
        for item in kap_items:
            title_text = item.title.text.strip() if item.title else ""
            link = item.link.text.strip() if item.link else ""
            desc = item.description.text.strip() if item.description else ""
            pub_date = item.pubDate.text.strip() if item.pubDate else datetime.now().isoformat()

            # Sadece watchlist hisselerini filtrele
            matched_stock = None
            for stock in stocks:
                if stock in title_text.upper() or stock in desc.upper():
                    matched_stock = stock
                    break
            if not matched_stock:
                continue

            # Body text: description alanı genellikle tam metni içeriyor
            body_text = bs4.BeautifulSoup(desc, 'html.parser').get_text(separator=' ', strip=True)
            raw_text = f"BAŞLIK: {title_text}\n\nBİLDİRİM DETAYI:\n{body_text}" if body_text else f"BAŞLIK: {title_text}"

            try:
                c.execute('''INSERT INTO kap_notifications
                    (stock_code, category, title, publish_date, link, summary, is_read)
                    VALUES (?, ?, ?, ?, ?, ?, 0)''',
                    (matched_stock, categorize(title_text),
                     f"{matched_stock} - {title_text[:120]}",
                     pub_date, link or f"{matched_stock}_{title_text[:30]}",
                     raw_text))
                new_records += 1
            except sqlite3.IntegrityError:
                pass

    # --- KAP RSS boş geldiyse Google News fallback ---
    if not kap_items or new_records == 0:
        print("[SCRAPER] KAP RSS bos, Google News fallback kullaniliyor...")
        for i, stock in enumerate(stocks):
            if progress_callback:
                progress_callback(stock, (len(stocks) - i) * 3)
            print(f"  Google News: {stock} ({i+1}/{len(stocks)})")
            items = fetch_google_news_rss(stock)
            for item in items:
                title_text = item.title.text.strip() if item.title else f"{stock} Bildirimi"
                link = item.link.text.strip() if item.link else ""
                desc = item.description.text.strip() if item.description else ""
                pub_date = item.pubDate.text.strip() if item.pubDate else datetime.now().isoformat()
                body_text = bs4.BeautifulSoup(desc, 'html.parser').get_text(strip=True)
                raw_text = f"BAŞLIK: {title_text}\n\nİÇERİK:\n{body_text}" if body_text else f"BAŞLIK: {title_text}"
                try:
                    c.execute('''INSERT INTO kap_notifications
                        (stock_code, category, title, publish_date, link, summary, is_read)
                        VALUES (?, ?, ?, ?, ?, ?, 0)''',
                        (stock, categorize(title_text),
                         f"{stock} - {title_text[:120]}",
                         pub_date, link or f"{stock}_{title_text[:30]}",
                         raw_text))
                    new_records += 1
                except sqlite3.IntegrityError:
                    pass

    conn.commit()
    conn.close()
    print(f"[SCRAPER] Toplam {new_records} yeni kayit eklendi.")
    return new_records


if __name__ == "__main__":
    count = scan_kap_for_all_stocks(days_back=30)
    print(f"Bitti. {count} kayit eklendi.")
