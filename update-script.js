const admin = require('firebase-admin');
const fetch = require('node-fetch');

// --- Helper Functions ---
const fetchFinnhubPrice = async (symbol, apiKey) => {
  const url = `https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${apiKey}`;
  try {
    const res = await fetch(url);
    if (!res.ok) { console.error(`Finnhub quote API error for ${symbol}: ${res.status}`); return 0; }
    const data = await res.json();
    return data.c || 0;
  } catch (e) { console.error(`Failed to fetch ${symbol} from Finnhub`, e); return 0; }
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

// --- Main Execution ---
async function main() {
  try {
    const serviceAccount = JSON.parse(Buffer.from(process.env.FIREBASE_SERVICE_ACCOUNT_BASE64, 'base64').toString('utf8'));
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.DATABASE_URL
    });
    const db = admin.database();

    // 1. Fetch ALL Data
    const [investmentsSnap, realizedSnap] = await Promise.all([
        db.ref('investments').once('value'),
        db.ref('realized').once('value')
    ]);
    const investments = investmentsSnap.val() || {};
    const realized = realizedSnap.val() || {};
    
    if (Object.keys(investments).length === 0) { console.log("No active investments."); return admin.app().delete(); }
    
    const finnhubApiKey = process.env.FINNHUB_API_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    // 2. Update Live Prices
    const priceCache = {};
    await Promise.all(symbols.map(async (symbol) => {
        priceCache[symbol] = await fetchFinnhubPrice(symbol, finnhubApiKey);
    }));
    await db.ref('priceCache').set(priceCache);
    console.log("Updated price cache.");

    // 3. Calculate Totals
    let totalInvested = 0, currentVal = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        currentVal += inv.shares * (priceCache[inv.symbol] || 0);
    });
    const totalRealizedPL = Object.values(realized).reduce((sum, trade) => sum + (trade.pl || 0), 0);
    const currentUnrealizedPL = currentVal - totalInvested;
    const allTimeTotalPL = totalRealizedPL + currentUnrealizedPL;

    // 4. Handle Benchmark Dates
    const alphaApiKey = process.env.ALPHA_VANTAGE_KEY;
    const inceptionCache = (await db.ref('inceptionCache').once('value')).val() || {};
    
    // Date A: Current Strategy Inception
    const currentStartDateObj = new Date(Math.min(...Object.values(investments).map(inv => new Date(inv.date.split('/').reverse().join('-')))));
    const currentStartDate = currentStartDateObj.toLocaleDateString('en-GB');
    
    // Date B: All Time Start (Fixed)
    const fixedStartDate = "14/07/2025"; 

    // Fetch/Cache Start Prices
    let spyCurrentStartPrice = inceptionCache[currentStartDate.replace(/\//g, '-')] || 0;
    let spyFixedStartPrice = inceptionCache["FIXED_" + fixedStartDate.replace(/\//g, '-')] || 0;

    // If missing from cache, fetch from API
    if (spyCurrentStartPrice === 0) {
        console.log(`Fetching SPY price for current start: ${currentStartDate}`);
        spyCurrentStartPrice = await fetchHistoricalPrice('SPY', currentStartDate, alphaApiKey);
        if (spyCurrentStartPrice > 0) await db.ref(`inceptionCache/${currentStartDate.replace(/\//g, '-')}`).set(spyCurrentStartPrice);
    }

    if (spyFixedStartPrice === 0) {
        console.log(`Fetching SPY price for fixed start: ${fixedStartDate}`);
        spyFixedStartPrice = await fetchHistoricalPrice('SPY', fixedStartDate, alphaApiKey);
        if (spyFixedStartPrice > 0) await db.ref(`inceptionCache/FIXED_${fixedStartDate.replace(/\//g, '-')}`).set(spyFixedStartPrice);
    }
    
    // 5. Calculate Benchmark Returns
    const spyCurrentPrice = priceCache['SPY'] || 0;
    const benchmarkCache = { 
        current: { our: 0, spy: 0 },
        allTime: { our: 0, spy: 0 }
    };

    if (totalInvested > 0 && spyCurrentStartPrice > 0) {
        benchmarkCache.current.our = (currentUnrealizedPL / totalInvested) * 100;
        benchmarkCache.current.spy = ((spyCurrentPrice - spyCurrentStartPrice) / spyCurrentStartPrice) * 100;
    }

    if (totalInvested > 0 && spyFixedStartPrice > 0) {
        // Approximate 'all time invested' as current invested for simplicity of percentage calc
        benchmarkCache.allTime.our = (allTimeTotalPL / totalInvested) * 100;
        benchmarkCache.allTime.spy = ((spyCurrentPrice - spyFixedStartPrice) / spyFixedStartPrice) * 100;
    }

    await db.ref('benchmarkCache').set(benchmarkCache);
    console.log("Updated benchmark cache:", benchmarkCache);

    return admin.app().delete();

  } catch (e) {
    console.error("FATAL ERROR:", e);
    if (admin.apps.length) admin.app().delete();
    process.exit(1);
  }
}

main();
