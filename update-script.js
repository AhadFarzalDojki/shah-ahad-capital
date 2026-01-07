const admin = require('firebase-admin');
const fetch = require('node-fetch');

// --- Helper Functions ---
const fetchFinnhubPrice = async (symbol, apiKey) => {
  const url = `https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${apiKey}`;
  try {
    const res = await fetch(url);
    if (!res.ok) return 0;
    const data = await res.json();
    return data.c || 0;
  } catch (e) { return 0; }
};

const fetchHistoricalPrice = async (symbol, dateStr, apiKey) => {
    let targetDate = new Date(dateStr.split('/').reverse().join('-'));
    for (let i = 0; i < 7; i++) {
        const formattedDate = targetDate.toISOString().split('T')[0];
        const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=${symbol}&apikey=${apiKey}`;
        try {
            const r = await fetch(url);
            if (r.ok) {
                const d = await r.json();
                if (d?.["Time Series (Daily)"]?.[formattedDate]) {
                    console.log(`Found historical price for ${symbol} on ${formattedDate}`);
                    return parseFloat(d["Time Series (Daily)"][formattedDate]["4. close"]);
                }
            }
        } catch (error) { console.error(error); }
        targetDate.setDate(targetDate.getDate() - 1);
    }
    return 0;
};

async function main() {
  try {
    const serviceAccount = JSON.parse(Buffer.from(process.env.FIREBASE_SERVICE_ACCOUNT_BASE64, 'base64').toString('utf8'));
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.DATABASE_URL
    });
    const db = admin.database();

    // 1. Fetch Data
    const [invSnap, realSnap, cacheSnap] = await Promise.all([
        db.ref('investments').once('value'),
        db.ref('realized').once('value'),
        db.ref('inceptionCache').once('value')
    ]);

    const investments = invSnap.val(); 
    const realized = realSnap.val() || {};
    const inceptionCache = cacheSnap.val() || {};
    
    // 2. Update Live Prices
    const finnhubApiKey = process.env.FINNHUB_API_KEY;
    const priceCache = {};
    
    if (investments) {
        const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
        if (!symbols.includes('SPY')) symbols.push('SPY');
        await Promise.all(symbols.map(async (symbol) => {
            const p = await fetchFinnhubPrice(symbol, finnhubApiKey);
            if(p > 0) priceCache[symbol] = p;
        }));
        await db.ref('priceCache').set(priceCache);
    } else {
        // Even if no investments, get SPY for benchmark
        const spyPrice = await fetchFinnhubPrice('SPY', finnhubApiKey);
        if (spyPrice > 0) {
            priceCache['SPY'] = spyPrice;
            await db.ref('priceCache').set(priceCache);
        }
    }

    // 3. Calculate Totals
    let currentInvested = 0, currentVal = 0;
    if (investments) {
        Object.values(investments).forEach(inv => {
            currentInvested += inv.shares * inv.price;
            currentVal += inv.shares * (priceCache[inv.symbol] || 0);
        });
    }
    
    const totalRealizedPL = Object.values(realized).reduce((sum, trade) => sum + (trade.pl || 0), 0);
    const currentUnrealizedPL = currentVal - currentInvested;
    const allTimeTotalPL = totalRealizedPL + currentUnrealizedPL;

    // 4. Benchmark Calculations
    
    // --- UPDATED CONFIG ---
    const alphaApiKey = process.env.ALPHA_VANTAGE_KEY;
    const TOTAL_CAPITAL = 172.00; // $168 initial + $4 top-up
    const currentStartKey = "05-10-2025";
    const allTimeStartKey = "19-08-2025"; // New correct date
    // ----------------------

    // Check Cache / Fetch if missing
    let spyCurrentStart = inceptionCache[currentStartKey] || 0;
    let spyAllTimeStart = inceptionCache[allTimeStartKey] || 0;

    if (spyCurrentStart === 0) {
        console.log("Fetching Q4 start price...");
        spyCurrentStart = await fetchHistoricalPrice('SPY', currentStartKey, alphaApiKey);
        if (spyCurrentStart > 0) await db.ref(`inceptionCache/${currentStartKey}`).set(spyCurrentStart);
    }
    if (spyAllTimeStart === 0) {
        console.log("Fetching All Time start price...");
        spyAllTimeStart = await fetchHistoricalPrice('SPY', allTimeStartKey, alphaApiKey);
        if (spyAllTimeStart > 0) await db.ref(`inceptionCache/${allTimeStartKey}`).set(spyAllTimeStart);
    }

    const spyCurrentPrice = priceCache['SPY'] || 0;
    const benchmarkCache = { current: { our: 0, spy: 0 }, allTime: { our: 0, spy: 0 } };

    // A. Current Strategy
    if (currentInvested > 0 && spyCurrentStart > 0 && spyCurrentPrice > 0) {
        benchmarkCache.current.our = (currentUnrealizedPL / currentInvested) * 100;
        benchmarkCache.current.spy = ((spyCurrentPrice - spyCurrentStart) / spyCurrentStart) * 100;
    }

    // B. All Time (using Total Capital)
    if (spyAllTimeStart > 0 && spyCurrentPrice > 0) {
        benchmarkCache.allTime.our = (allTimeTotalPL / TOTAL_CAPITAL) * 100;
        benchmarkCache.allTime.spy = ((spyCurrentPrice - spyAllTimeStart) / spyAllTimeStart) * 100;
    }

    await db.ref('benchmarkCache').set(benchmarkCache);
    console.log("Updated benchmarks:", benchmarkCache);

    process.exit(0);
  } catch (e) {
    console.error("FATAL ERROR:", e);
    process.exit(1);
  }
}

main();
