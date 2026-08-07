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
            
        # Prepare batch input
        batch_input = []
        for row in batch:
            batch_input.append({
                "id": row['id'],
                "stock": row['stock_code'],
                "text": row['summary']
            })
            
        prompt = f"""
        Aşağıdaki KAP bildirimini profesyonel bir yatırımcı bakış açısıyla analiz et.
        DİKKAT KESİNLİKLE UYMAN GEREKEN KURALLAR:
        1. ASLA BAŞKA HİSSE İSMİ KARIŞTIRMA! Sadece gelen verideki '{batch[0]['stock_code']}' hissesine ait bilgileri yaz!
        2. ASLA SAHTE VEYA ÖRNEK VERİ UYDURMA!
        3. SADECE aşağıda "Gelen Veri" bölümünde sana verdiğim GERÇEK 'text' içeriğini oku ve özetle.
        4. Metinde rakam yoksa kesinlikle 'veri yok' yaz.
        5. JSON Object formatında çıktı ver. Mutlaka bir "notifications" anahtarı olsun ve değeri DİZİ (Array) olsun.
        
        Gelen Veri (BURADAKİ TEXTLERİ KULLAN):
        {json.dumps(batch_input, ensure_ascii=False)}
        
        İstenen JSON Formatı:
        {{
            "notifications": [
                {{
                    "id": <GELEN VERİDEKİ ID İLE AYNI OLMALI>,
                    "summary": "Metindeki gerçek olayın 2-3 cümlelik özeti",
                    "positive_side": "Gerçek kazanımlar (yoksa 'Veri yok' yaz)",
                    "negative_side": "Gerçek riskler (yoksa 'Veri yok' yaz)",
                    "signal": "Pozitif, Negatif veya Nötr",
                    "kap_impact": 7,
                    "financial_effect": "Finansal etki (yoksa 'Veri yok' yaz)"
                }}
            ]
        }}
        """
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model="llama-3.3-70b-versatile",
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
                print(f"Successfully batch analyzed KAP {res.get('id')} using Groq")
            
            conn.commit()
            time.sleep(2) # Groq has 30 RPM limits on free tier, 2s is safe
            
        except Exception as e:
            print(f"Error processing batch with Groq: {e}")
            if "429" in str(e) or "rate" in str(e).lower():
                print("Rate limit hit on 70B model, falling back to llama-3.1-8b-instant (which has 500,000+ TPD limit)...")
                time.sleep(3)
                # Retry once using 8B model (which has 5x higher quota!)
                try:
                    response = client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
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
                    conn.commit()
                except Exception as e2:
                    print(f"Retry with 8B model failed: {e2}")
            elif "400" in str(e) or "json_validate_failed" in str(e).lower():
                print("JSON validation failed by Llama 3, skipping batch for now, will retry next run.")
                time.sleep(2)
            else:
                time.sleep(2)
            
    conn.close()

if __name__ == "__main__":
    analyze_unread_notifications()
