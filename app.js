let financials = {};
let stocks = [];
let kaps = [];

// Filter states
let currentSignal = 'Tümü';
let currentStock = 'Tümü';

async function init() {
    updateClock();
    setInterval(updateClock, 1000);
    
    await loadStocks();
    await loadFinancials();
    await loadKapNotifications();
}

function isFutureQuarter(qStr) {
    if (!qStr || qStr.length !== 6) return false;
    const year = parseInt(qStr.substring(0, 4));
    const q = parseInt(qStr.substring(5, 6));
    
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;
    const currentQuarter = Math.ceil(currentMonth / 3);
    
    if (year > currentYear) return true;
    if (year === currentYear && q > currentQuarter) return true;
    return false;
}

function updateClock() {
    const now = new Date();
    const opts = { day: '2-digit', month: 'short', weekday: 'short', hour: '2-digit', minute:'2-digit', second:'2-digit' };
    document.getElementById('clockDisplay').innerText = now.toLocaleDateString('tr-TR', opts).replace(',', ' -');
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.menu-item').forEach(el => el.classList.remove('active'));
    
    if (tabId === 'kap') {
        document.getElementById('kapTab').style.display = 'flex';
        document.querySelectorAll('.menu-item')[0].classList.add('active');
    } else if (tabId === 'heatmap') {
        document.getElementById('heatmapTab').style.display = 'flex';
        document.querySelectorAll('.menu-item')[1].classList.add('active');
        // REFRESH FINANCIALS EVERY TIME TAB IS CLICKED
        loadFinancials();
    }
}

async function loadStocks() {
    const res = await fetch('/api/stocks');
    const data = await res.json();
    stocks = Array.isArray(data) ? data : (data.stocks || []);
    
    // Populate stock filter dropdown
    const stockSelect = document.getElementById('stockFilter');
    if (stockSelect) {
        stockSelect.innerHTML = `<option value="Tümü">Tümü (${stocks.length} Hisse)</option>` + stocks.map(s => `<option value="${s}">${s}</option>`).join('');
    }
    
    // Populate modal list
    const list = document.getElementById('stockList');
    if (list) {
        list.innerHTML = '';
        stocks.forEach(s => {
            list.innerHTML += `
                <div>
                    <span>${s}</span>
                    <button class="outline-btn" style="padding:0.2rem 0.5rem; font-size:0.7rem; border-color:#ef4444; color:#ef4444;" onclick="removeStock('${s}')">Sil</button>
                </div>
            `;
        });
    }
}

function selectStockFilter(stock) {
    currentStock = stock;
    const stockSelect = document.getElementById('stockFilter');
    if (stockSelect && stockSelect.value !== stock) {
        stockSelect.value = stock;
    }
    renderKaps();
}

function selectSignalFilter(signal, el) {
    currentSignal = signal;
    document.querySelectorAll('#signalPillGroup .pill').forEach(item => item.classList.remove('active'));
    el.classList.add('active');
    renderKaps();
}

function clearFilters() {
    document.getElementById('impactSlider').value = 0;
    document.getElementById('impactValue').innerText = '0';
    document.getElementById('dateFilter').value = '';
    document.getElementById('categoryFilter').value = 'Tümü';
    
    const stockSelect = document.getElementById('stockFilter');
    if (stockSelect) stockSelect.value = 'Tümü';
    
    currentStock = 'Tümü';
    currentSignal = 'Tümü';
    
    document.querySelectorAll('#signalPillGroup .pill').forEach(item => item.classList.remove('active'));
    document.querySelector('#signalPillGroup .pill').classList.add('active'); // Tümü
    
    renderKaps();
}

async function addStock() {
    const input = document.getElementById('newStockInput');
    const code = input.value.trim().toUpperCase();
    if(!code) return;
    
    await fetch('/api/stocks', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({code}) });
    input.value = '';
    await loadStocks();
    await loadFinancials();
}

async function removeStock(code) {
    await fetch(`/api/stocks/${code}`, { method: 'DELETE' });
    if(currentStock === code) currentStock = 'Tümü';
    await loadStocks();
    await loadFinancials();
}

async function loadFinancials() {
    renderHeatmap();
}

async function renderHeatmap() {
    const table = document.getElementById('heatmapTable');
    const metric = document.getElementById('metricSelector').value;
    
    try {
        const res = await fetch(`/api/financials/html?metric=${metric}`);
        const html = await res.text();
        table.innerHTML = html;
    } catch (e) {
        console.error(e);
        table.innerHTML = "<tr><td class='empty-state'>Bir hata oluştu.</td></tr>";
    }
}

async function loadKapNotifications() {
    renderKaps();
}

async function renderKaps() {
    const minImpact = parseInt(document.getElementById('impactSlider').value) || 0;
    const cat = document.getElementById('categoryFilter').value;
    const dateStr = document.getElementById('dateFilter').value;
    
    try {
        const url = `/api/kap/html?stock=${encodeURIComponent(currentStock)}&signal=${encodeURIComponent(currentSignal)}&minImpact=${minImpact}&category=${encodeURIComponent(cat)}&dateStr=${encodeURIComponent(dateStr)}`;
        const res = await fetch(url);
        const data = await res.json();
        
        // Update Stats
        document.getElementById('statTotal').innerText = data.stats.total;
        document.getElementById('statPositive').innerText = data.stats.positive;
        document.getElementById('statNegative').innerText = data.stats.negative;
        document.getElementById('statHighImpact').innerText = data.stats.high;
        
        const grid = document.getElementById('kapGrid');
        const emptyState = document.getElementById('emptyState');
        
        if (data.stats.total === 0) {
            grid.style.display = 'none';
            emptyState.style.display = 'flex';
        } else {
            emptyState.style.display = 'none';
            grid.style.display = 'grid';
            grid.innerHTML = data.html;
        }
    } catch(e) {
        console.error("Error loading KAP html:", e);
    }
}

let scanPollInterval;

async function triggerManualScan() {
    const btn = document.getElementById('manualScanBtn');
    const statusText = document.getElementById('scanStatusText');
    
    btn.disabled = true;
    btn.innerHTML = "Taranıyor...";
    
    await fetch('/api/kap/manual-scan', {method: 'POST'});
    
    statusText.style.display = 'block';
    
    let localRemainingSeconds = 0;
    
    scanPollInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/kap/status');
            const state = await res.json();
            
            if (state.is_active) {
                if (statusText.dataset.currentStock !== state.current_stock || localRemainingSeconds === 0) {
                    statusText.dataset.currentStock = state.current_stock;
                    localRemainingSeconds = state.remaining_seconds;
                } else {
                    if (localRemainingSeconds > 0) localRemainingSeconds--;
                }
                
                btn.innerHTML = `Taranıyor...`;
                statusText.innerText = `${state.current_stock} taranıyor... Kalan: ~${localRemainingSeconds}sn`;
            } else {
                clearInterval(scanPollInterval);
                btn.disabled = false;
                btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h4l2-9 5 18 3-10h4"/></svg> Manuel Tara`;
                statusText.style.display = 'none';
                
                await loadKapNotifications();
                await loadFinancials(); // <--- FIXED: Reload heatmap data when scan finishes!
                showToast("Tarama tamamlandı!");
                
                const badge = document.getElementById('newAlertBadge');
                badge.style.display = 'block';
                setTimeout(() => badge.style.display = 'none', 5000);
                statusText.dataset.currentStock = "";
            }
        } catch (e) {
            console.error(e);
        }
    }, 1000);
}

function openAddStockModal() { document.getElementById('stockModal').classList.add('active'); }
function closeAddStockModal() { document.getElementById('stockModal').classList.remove('active'); }
function showToast(msg) {
    const toast = document.getElementById('toast');
    toast.innerText = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 4000);
}

init();
