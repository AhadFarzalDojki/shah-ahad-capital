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

async function main() {
  try {
    const serviceAccount = JSON.parse(Buffer.from(process.env.FIREBASE_SERVICE_ACCOUNT_BASE64, 'base64').toString('utf8'));
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.DATABASE_URL
    });
    const db = admin.database();

    // 1. Fetch All Data
    const [invSnap, realSnap, cacheSnap] = await Promise.all([
        db.ref('investments').once('value'),
        db.ref('realized').once('value'),
        db.ref('inceptionCache').once('value')
    ]);

    const investments = invSnap.val(); // can be null
    const realized = realSnap.val() || {};
    const inceptionCache = cacheSnap.val() || {};
    
    // 2. Update Live Prices (Only if we have investments)
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
        console.log("Updated prices.");
    } else {
        // Even with no investments, we need SPY price for the benchmark
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
    
    // 4. Benchmark Calculations
    const currentStartKey = "05-10-2025"; // Start of Q4 (Will be updated for Q1 2026 later)
    const spyCurrentStart = inceptionCache[currentStartKey] || 0;
    
    const allTimeStartKey = "14-07-2025";
    const spyAllTimeStart = inceptionCache[allTimeStartKey] || 0;
    
    const spyCurrentPrice = priceCache['SPY'] || 0;
    const INITIAL_CAPITAL = 160.00; // Hardcoded initial investment for All Time Calc

    const benchmarkCache = {
        current: { our: 0, spy: 0 },
        allTime: { our: 0, spy: 0 }
    };

    // A. Current Strategy (Only if active investments exist)
    if (currentInvested > 0 && spyCurrentStart > 0 && spyCurrentPrice > 0) {
        benchmarkCache.current.our = (currentUnrealizedPL / currentInvested) * 100;
        benchmarkCache.current.spy = ((spyCurrentPrice - spyCurrentStart) / spyCurrentStart) * 100;
    } 
    // If no active investments, Current Strategy is 0.00% (Correct)

    // B. All Time (Always calculated)
    // Formula: (Total Realized P/L + Current Unrealized P/L) / Initial Capital
    const allTimeTotalPL = totalRealizedPL + currentUnrealizedPL;
    
    if (spyAllTimeStart > 0 && spyCurrentPrice > 0) {
        benchmarkCache.allTime.our = (allTimeTotalPL / INITIAL_CAPITAL) * 100;
        benchmarkCache.allTime.spy = ((spyCurrentPrice - spyAllTimeStart) / spyAllTimeStart) * 100;
    }

    await db.ref('benchmarkCache').set(benchmarkCache);
    console.log("Updated benchmark cache:", benchmarkCache);

    process.exit(0);

  } catch (e) {
    console.error("FATAL ERROR:", e);
    process.exit(1);
  }
}

main();
