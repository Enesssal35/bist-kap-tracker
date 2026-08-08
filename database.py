import sqlite3
from datetime import datetime
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "bist_tracker.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # Stocks Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL
        )
    ''')

    # Insert default stocks if none exist
    c.execute('SELECT COUNT(*) FROM stocks')
    if c.fetchone()[0] == 0:
        default_stocks = ['BRSAN', 'PGSUS', 'EGEEN', 'FROTO', 'CCOLA', 'CLEBI', 'OTKAR', 'ISMEN', 'ANSGR', 'LOGO', 'LKMNH', 'ALKA', 'ALTNY', 'SDTTR']
        for stock in default_stocks:
            c.execute('INSERT INTO stocks (code) VALUES (?)', (stock,))

    # Financials Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS financials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            quarter TEXT NOT NULL, -- e.g., "2023Q1"
            net_income REAL,
            equity REAL,
            nopat REAL,
            invested_capital REAL,
            wacc REAL,
            roe REAL,
            roic REAL,
            UNIQUE(stock_code, quarter)
        )
    ''')

    # KAP Notifications Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS kap_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            category TEXT,
            title TEXT,
            publish_date TEXT,
            link TEXT UNIQUE,
            summary TEXT,
            positive_side TEXT,
            negative_side TEXT,
            signal TEXT, -- Positive, Negative, Neutral
            kap_impact INTEGER, -- 1-10
            financial_effect TEXT,
            is_read INTEGER DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
