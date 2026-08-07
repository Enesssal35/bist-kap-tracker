import requests
import sqlite3
import os
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "bist_tracker.db")

def get_stocks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code FROM stocks')
    stocks = [row[0] for row in c.fetchall()]
    conn.close()
    return stocks

def fetch_quarterly_data_isyatirim(stock_code, year1, period1, year2, period2, year3, period3, year4, period4):
    url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
    params = {
        'companyCode': stock_code,
        'exchange': 'TRY',
        'financialGroup': 'XI_29',
        'year1': year1, 'period1': period1,
        'year2': year2, 'period2': period2,
        'year3': year3, 'period3': period3,
        'year4': year4, 'period4': period4
    }
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if data.get('ok') and data.get('value'):
            return data['value']
    except Exception as e:
        print(f"Error fetching {stock_code} {year1}/{period1}: {e}")
    return None

def parse_financials(raw_data, col_index):
    val_key = f'value{col_index}'
    
    def get_val_by_code(codes):
        for item in raw_data:
            if item.get('itemCode') in codes and item.get(val_key) is not None:
                try:
                    return float(item[val_key])
                except:
                    pass
        return 0.0

    # '31' is Equity for banks/insurance, '3' is Net Income, '44' / '45' for some others.
    net_income = get_val_by_code(['3Z', '3L', '3'])
    equity = get_val_by_code(['2N', '2O', '31'])
    operating_profit = get_val_by_code(['3DF', '3H', '34', '35'])
    pre_tax_profit = get_val_by_code(['3I', '37'])
    tax_expense = get_val_by_code(['3IA', '42'])
    
    total_assets = get_val_by_code(['1BL', '1'])
    cash = get_val_by_code(['1AA', '1A01', '1A'])
    short_term_debt = get_val_by_code(['2A', '3A'])
    
    # Fallback for Total Assets
    if total_assets == 0:
        total_assets = get_val_by_code(['1A']) + get_val_by_code(['1AK'])

    # Tax Rate
    tax_rate = 0.20 # Default
    if pre_tax_profit > 0 and tax_expense < 0:
        tax_rate = abs(tax_expense) / pre_tax_profit
    elif pre_tax_profit > 0 and tax_expense > 0:
         tax_rate = tax_expense / pre_tax_profit
    
    # NOPAT
    nopat = operating_profit * (1 - min(max(tax_rate, 0), 0.5)) 
    
    # Invested Capital
    invested_capital = total_assets - cash - short_term_debt
    if invested_capital <= 0:
        invested_capital = equity # fallback
        
    return {
        'net_income': net_income,
        'equity': equity,
        'nopat': nopat,
        'invested_capital': invested_capital
    }

def update_all_stocks_live():
    stocks = get_stocks()
    now = datetime.now()
    current_year = now.year
    
    # We will fetch last 5 years
    years_to_fetch = list(range(current_year - 5, current_year + 1))
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    for stock in stocks:
        print(f"Fetching live data for {stock}...")
        for y_idx in range(len(years_to_fetch)):
            y = years_to_fetch[y_idx]
            
            # Fetch Q1 to Q4 for year y. Is Yatirim groups by 4 periods per request.
            raw_data = fetch_quarterly_data_isyatirim(stock, y, 3, y, 6, y, 9, y, 12)
            if not raw_data:
                time.sleep(1)
                continue
            
            periods = [(1, f"{y}Q1"), (2, f"{y}Q2"), (3, f"{y}Q3"), (4, f"{y}Q4")]
            
            for col_idx, q_str in periods:
                fin = parse_financials(raw_data, col_idx)
                
                if fin['equity'] == 0: # Probably period hasn't been reported yet
                    continue
                
                # Annualize for ROE/ROIC calculation since these are cumulative quarterly values in TR accounting
                # Q1: *4, Q2: *2, Q3: *4/3, Q4: *1
                annualize_factor = 1
                q_num = col_idx
                if q_num == 1: annualize_factor = 4
                elif q_num == 2: annualize_factor = 2
                elif q_num == 3: annualize_factor = 4/3
                elif q_num == 4: annualize_factor = 1
                
                ann_net_income = fin['net_income'] * annualize_factor
                ann_nopat = fin['nopat'] * annualize_factor
                
                roe = ann_net_income / fin['equity'] if fin['equity'] > 0 else 0
                roic = ann_nopat / fin['invested_capital'] if fin['invested_capital'] > 0 else 0
                
                # Assume WACC is roughly 35% in TR for currently active period, but let's use a dynamic dummy or fixed proxy
                # Real WACC calculation requires fetching risk free rate (10Y TR bonds) and beta. 
                wacc = 0.35
                
                c.execute('''
                    INSERT INTO financials (
                        stock_code, quarter, net_income, equity, nopat, invested_capital, wacc, roe, roic
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stock_code, quarter) DO UPDATE SET
                        net_income=excluded.net_income,
                        equity=excluded.equity,
                        nopat=excluded.nopat,
                        invested_capital=excluded.invested_capital,
                        wacc=excluded.wacc,
                        roe=excluded.roe,
                        roic=excluded.roic
                ''', (stock, q_str, fin['net_income'], fin['equity'], fin['nopat'], fin['invested_capital'], wacc, roe, roic))
            
            time.sleep(1) # Prevent rate limits on Is Yatirim
        conn.commit()
    conn.close()
    print("Live financial data update complete.")

if __name__ == "__main__":
    update_all_stocks_live()
