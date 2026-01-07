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
    // 1. Initialize Firebase
    const serviceAccount = JSON.parse(Buffer.from(process.env.FIREBASE_SERVICE_ACCOUNT_BASE64, 'base64').toString('utf8'));
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.DATABASE_URL
    });
    const db = admin.database();

    // 2. Fetch All Data
    const [invSnap, realSnap, cacheSnap] = await Promise.all([
        db.ref('investments').once('value'),
        db.ref('realized').once('value'),
        db.ref('inceptionCache').once('value')
    ]);

    const investments = invSnap.val() || {};
    const realized = realSnap.val() || {};
    const inceptionCache = cacheSnap.val() || {};

    if (Object.keys(investments).length === 0) {
        console.log("No investments.");
        process.exit(0);
    }
    
    // 3. Update Live Prices (Finnhub)
    const finnhubApiKey = process.env.FINNHUB_API_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    const priceCache = {};
    await Promise.all(symbols.map(async (symbol) => {
        const p = await fetchFinnhubPrice(symbol, finnhubApiKey);
        if(p > 0) priceCache[symbol] = p;
    }));
    await db.ref('priceCache').set(priceCache);
    console.log("Updated prices.");

    // 4. Calculate Portfolio Totals
    let totalInvested = 0, currentVal = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        currentVal += inv.shares * (priceCache[inv.symbol] || 0);
    });
    
    const totalRealizedPL = Object.values(realized).reduce((sum, trade) => sum + (trade.pl || 0), 0);
    const currentUnrealizedPL = currentVal - totalInvested;
    const allTimeTotalPL = totalRealizedPL + currentUnrealizedPL;

    // 5. Benchmark Calculations
    // A. Current Strategy (Since Oct 5)
    const currentStartKey = "05-10-2025";
    const spyCurrentStart = inceptionCache[currentStartKey] || 0;
    
    // B. All Time (Since July 14)
    const allTimeStartKey = "14-07-2025";
    const spyAllTimeStart = inceptionCache[allTimeStartKey] || 0;
    
    const spyCurrentPrice = priceCache['SPY'] || 0;

    const benchmarkCache = {
        current: { our: 0, spy: 0 },
        allTime: { our: 0, spy: 0 }
    };

    // Calculate Current
    if (totalInvested > 0 && spyCurrentStart > 0 && spyCurrentPrice > 0) {
        benchmarkCache.current.our = (currentUnrealizedPL / totalInvested) * 100;
        benchmarkCache.current.spy = ((spyCurrentPrice - spyCurrentStart) / spyCurrentStart) * 100;
    }

    // Calculate All Time
    if (totalInvested > 0 && spyAllTimeStart > 0 && spyCurrentPrice > 0) {
        // For All Time Return, we use (Total P/L / Current Invested) as a simple approximation for the dashboard
        benchmarkCache.allTime.our = (allTimeTotalPL / totalInvested) * 100;
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
