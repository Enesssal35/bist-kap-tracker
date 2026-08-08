import sqlite3
import os
import json
import time
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.path.join(os.path.dirname(__file__), "bist_tracker.db")

def analyze_unread_notifications(progress_callback=None):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY not found in .env")
        return
        
    client = Groq(api_key=api_key)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('SELECT * FROM kap_notifications WHERE is_read = 0')
    unread = c.fetchall()
    total = len(unread)
    
    if total == 0:
        conn.close()
        return

    # Process 1 by 1 to prevent stock cross-contamination
    batch_size = 1
    
    for i in range(0, total, batch_size):
        batch = unread[i:i+batch_size]
        
        if progress_callback:
            # Estimate 3 seconds per remaining batch (Groq is faster)
            remaining_batches = (total - i) // batch_size + 1
            progress_callback(batch[0]['stock_code'], remaining_batches * 3)
            
        # Prepare batch input — include full raw body text scraped from KAP page
        batch_input = []
        for row in batch:
            # 'summary' column holds the raw_text scraped from the KAP bildirim page
            body_text = row['summary'] or ""
            batch_input.append({
                "id": row['id'],
                "stock": row['stock_code'],
                "category": row['category'],
                "title": row['title'],
                "bildirim_body": body_text  # Full scraped body text from KAP page
            })

        prompt = f"""
        Sen profesyonel bir hisse senedi ve finansal veri analistisin.
        
        Görevin: Aşağıdaki KAP (Kamuyu Aydınlatma Platformu) bildiriminin tam metnini oku ve sadece o metindeki somut, doğrulanmış verilere dayanarak analiz üret.

        ÖNEMLİ KURALLAR:
        1. "bildirim_body" alanındaki KAP metninin içindeki GERÇEK rakamları, tutarları, tarihleri ve tarafları kullan.
        2. Metinde finansal rakam veya etki belirtilmemişse asla varsayımsal sayı uydurma → 'Veri yok' yaz.
        3. Sadece '{batch[0]['stock_code']}' hissesini analiz et, başka hisse karıştırma.
        4. Profesyonel, kurumsal ve abartısız bir dil kullan.
        5. JSON Object formatında çıktı ver.

        Analiz Edilecek KAP Bildirimi:
        {json.dumps(batch_input, ensure_ascii=False)}

        İstenen JSON Formatı:
        {{
            "notifications": [
                {{
                    "id": {batch[0]['id']},
                    "category": "Bildirimin gerçek kategorisi (ör: {batch[0]['stock_code']} - Finansal Rapor)",
                    "title": "Bildirimin içeriğini özetleyen kısa ve çarpıcı başlık",
                    "summary": "KAP metniндeki rakamlar, tarihler ve tarafları içeren 2-3 cümlelik özet",
                    "positive_side": "Nakit akışı, marj, pazar payı veya operasyonel kazanım (metinde yoksa → 'Veri yok')",
                    "negative_side": "Kur, maliyet, sektörel veya uygulama riskleri (metinde yoksa → 'Veri yok')",
                    "signal": "Pozitif, Negatif veya Nötr",
                    "kap_impact": 5,
                    "financial_effect": "Metinde yeterli veri varsa ROE/ROIC/WACC veya Net EVA üzerine yönsel etki. Yoksa → 'Yönsel veri yok'"
                }}
            ]
        }}
        """
        
        # Primary call with llama-3.1-8b-instant (500,000+ TPD quota, super fast)
        try:
            response = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"},
            )
            
            raw_json = response.choices[0].message.content
            results = json.loads(raw_json).get("notifications", [])
            
            for res in results:
                c.execute('''
                    UPDATE kap_notifications 
                    SET summary = ?, positive_side = ?, negative_side = ?, signal = ?, kap_impact = ?, financial_effect = ?, is_read = 1
                    WHERE id = ?
                ''', (
                    res.get("summary", "Analiz yapılamadı"),
                    res.get("positive_side", "Veri yok"),
                    res.get("negative_side", "Veri yok"),
                    res.get("signal", "Nötr"),
                    res.get("kap_impact", 5),
                    res.get("financial_effect", "Veri yok"),
                    res.get("id")
                ))
                print(f"Successfully batch analyzed KAP {res.get('id')} using Groq 8B")
            
            conn.commit()
            time.sleep(1) # Faster limits on 8B
            
        except Exception as e:
            print(f"Error processing batch with Groq: {e}")
            time.sleep(2)
            
    conn.close()

if __name__ == "__main__":
    analyze_unread_notifications()
