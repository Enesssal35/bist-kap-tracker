"""
reset_db.py — Veritabanını tamamen temizler, watchlist hisselerini yeniden ekler,
kap_scraper ile canlı KAP bildirimlerini (body text dahil) çeker,
ardından llm_analyzer ile Groq AI analizini çalıştırır.
"""
import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "bist_tracker.db")

WATCHLIST = [
    'BRSAN', 'PGSUS', 'EGEEN', 'FROTO', 'CCOLA',
    'CLEBI', 'OTKAR', 'ISMEN', 'ANSGR', 'LOGO',
    'LKMNH', 'ALKA', 'ALTNY', 'SDTTR'
]

def reset_db():
    print("=" * 60)
    print("ADIM 1/3 - Veritabani temizleniyor...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM kap_notifications")
    c.execute("DELETE FROM stocks")
    for code in WATCHLIST:
        c.execute("INSERT INTO stocks (code) VALUES (?)", (code,))
    conn.commit()
    conn.close()
    print(f"  OK {len(WATCHLIST)} hisse watchlist'e yuklendi: {', '.join(WATCHLIST)}")

    print()
    print("ADIM 2/3 - KAP bildirimleri cekiliyor (body text dahil)...")
    from kap_scraper import scan_kap_for_all_stocks
    count = scan_kap_for_all_stocks(days_back=30)
    print(f"  OK {count} yeni kayit veritabanina eklendi.")

    print()
    print("ADIM 3/3 - Groq AI ile bildirimler analiz ediliyor...")
    from llm_analyzer import analyze_unread_notifications
    analyze_unread_notifications()
    print("  OK Analiz tamamlandi.")

    print()
    print("=" * 60)
    print("reset_db.py basariyla tamamlandi! Site hazir.")
    print("=" * 60)

if __name__ == "__main__":
    reset_db()
