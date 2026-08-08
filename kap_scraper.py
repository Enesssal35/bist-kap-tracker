import requests
import sqlite3
import os
import re
import bs4
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "bist_tracker.db")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
    'Accept-Encoding': 'identity',
    'Referer': 'https://www.kap.org.tr/tr/BildirimSorgu'
}

def get_stocks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code FROM stocks')
    stocks = [row[0] for row in c.fetchall()]
    conn.close()
    return stocks


def scrape_kap_body_text(bildirim_url):
    """
    Given a https://www.kap.org.tr/tr/Bildirim/<id> URL,
    fetches the page and extracts the full disclosure body text
    from the embedded React Server Component payloads (self.__next_f.push scripts).
    Returns plain text string.
    """
    try:
        r = requests.get(bildirim_url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return ""
        r.encoding = 'utf-8'
        soup = bs4.BeautifulSoup(r.text, 'html.parser')

        full_payload = ""
        for script in soup.find_all('script'):
            txt = script.get_text()
            if 'self.__next_f.push' in txt or 'u003c' in txt.lower():
                full_payload += txt

        if not full_payload:
            return ""

        # Decode unicode escapes (\u003c → < etc.)
        try:
            decoded = full_payload.encode('utf-8').decode('unicode_escape', errors='replace')
        except Exception:
            decoded = full_payload

        # Extract embedded HTML tables/sections
        inner_soup = bs4.BeautifulSoup(decoded, 'html.parser')

        # Remove nav/header noise
        for tag in inner_soup.find_all(['nav', 'header', 'footer', 'script', 'style', 'button']):
            tag.decompose()

        # Get meaningful text from tables and paragraphs
        body_parts = []
        for el in inner_soup.find_all(['td', 'th', 'p', 'li', 'h1', 'h2', 'h3', 'span', 'div']):
            text = el.get_text(separator=' ', strip=True)
            # Only keep lines with enough content and Turkish/financial keywords
            if len(text) > 30 and not text.startswith('function') and not text.startswith('//'):
                body_parts.append(text)

        # Deduplicate while preserving order
        seen = set()
        unique_parts = []
        for part in body_parts:
            key = part[:60]
            if key not in seen:
                seen.add(key)
                unique_parts.append(part)

        full_text = ' | '.join(unique_parts[:40])  # limit to first 40 meaningful sections
        return full_text[:4000]  # max 4000 chars to stay within token limits

    except Exception as e:
        print(f"  [scrape_kap_body_text] Error for {bildirim_url}: {e}")
        return ""


def fetch_kap_notifications(stock_code, from_date, to_date):
    """
    1. Fetches real live KAP disclosures via Google News RSS feed for the stock.
    2. For each found disclosure with a KAP bildirim link, scrapes the full body text.
    """
    rss_url = f"https://news.google.com/rss/search?q=KAP+%22{stock_code}%22&hl=tr&gl=TR&ceid=TR:tr"

    real_notifications = []
    try:
        r = requests.get(rss_url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return real_notifications

        r.encoding = 'utf-8'
        soup = bs4.BeautifulSoup(r.text, 'xml')
        items = soup.find_all('item')[:5]

        for item in items:
            title_text = item.title.text.strip() if item.title else f"{stock_code} KAP Bildirimi"
            news_link  = item.link.text.strip() if item.link else ""

            # Category detection
            category = "Özel Durum Açıklaması"
            tl = title_text.lower()
            if "faaliyet raporu" in tl: category = "Faaliyet Raporu"
            elif "finansal" in tl or "bilanço" in tl or "sonuç" in tl: category = "Finansal Rapor"
            elif "sözleşme" in tl or "sipariş" in tl or "ihale" in tl or "anlaşma" in tl: category = "Yeni Sipariş/Sözleşme"
            elif "sermaye" in tl or "bedelsiz" in tl or "spk" in tl: category = "Sermaye Artırımı"
            elif "teşvik" in tl: category = "Teşvik"
            elif "yatırım" in tl or "capex" in tl: category = "Duran Varlık Alımı"

            # Try to identify a direct KAP Bildirim URL from the title or description
            # KAP canonical link is often mentioned in the RSS item's full description
            description = item.description.text if item.description else ""
            kap_link_match = re.search(r'https://www\.kap\.org\.tr/tr/Bildirim/(\d+)', description + title_text + news_link)

            if kap_link_match:
                kap_url = f"https://www.kap.org.tr/tr/Bildirim/{kap_link_match.group(1)}"
            else:
                # Fall back to company summary page
                kap_url = f"https://www.kap.org.tr/tr/sirket-bilgileri/ozet/{stock_code}"

            # Scrape full body text from the KAP notification page
            print(f"  Scraping body for {stock_code}: {kap_url}")
            body_text = scrape_kap_body_text(kap_url) if "Bildirim" in kap_url else ""

            # If body text not found from KAP page, use the RSS description as fallback
            if not body_text:
                body_text = bs4.BeautifulSoup(description, 'html.parser').get_text(strip=True)

            # Combine for raw_text
            raw_text = f"BAŞLIK: {title_text}\n\nBİLDİRİM DETAYI:\n{body_text}" if body_text else f"BAŞLIK: {title_text}"

            real_notifications.append({
                "stock_code": stock_code,
                "category": category,
                "title": f"{stock_code} - {title_text[:120]}",
                "publish_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "link": kap_url,
                "raw_text": raw_text
            })

    except Exception as e:
        print(f"[fetch_kap_notifications] Error for {stock_code}: {e}")

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
            progress_callback(stock, (total - i) * 3)

        print(f"Scanning {stock} ({i+1}/{total})...")
        notifs = fetch_kap_notifications(stock, from_date, to_date)
        for notif in notifs:
            try:
                c.execute('''
                    INSERT INTO kap_notifications (
                        stock_code, category, title, publish_date, link, summary, is_read
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    notif['stock_code'], notif['category'], notif['title'],
                    notif['publish_date'], notif['link'], notif['raw_text'], 0
                ))
                new_records += 1
            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()
    return new_records


if __name__ == "__main__":
    count = scan_kap_for_all_stocks(days_back=180)
    print(f"Scanned KAP. Added {count} new records to summarize.")
