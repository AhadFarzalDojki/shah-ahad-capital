const admin = require('firebase-admin');
const fetch = require('node-fetch');

// 1. Fetch Live Prices (Finnhub - Fast)
const fetchFinnhubPrice = async (symbol, apiKey) => {
  try {
    const res = await fetch(`https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${apiKey}`);
    if (!res.ok) return 0;
    const data = await res.json();
    return data.c || 0;
  } catch (e) { return 0; }
};

// 2. Fetch Historical Price (Alpha Vantage - Slow, Limited)
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
    admin.initializeApp({ credential: admin.credential.cert(serviceAccount), databaseURL: process.env.DATABASE_URL });
    const db = admin.database();

    const investments = (await db.ref('investments').once('value')).val();
    if (!investments) return process.exit(0);
    
    // A. Update Prices
    const finnhubKey = process.env.FINNHUB_API_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    const priceCache = {};
    await Promise.all(symbols.map(async (symbol) => {
        const price = await fetchFinnhubPrice(symbol, finnhubKey);
        if (price > 0) priceCache[symbol] = price;
    }));
    await db.ref('priceCache').set(priceCache);
    console.log("Updated prices.");

    // B. Update Benchmark (With Smart Cache)
    let totalInvested = 0, totalValue = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        totalValue += inv.shares * (priceCache[inv.symbol] || 0);
    });

    const earliestDateStr = Object.values(investments).map(inv => new Date(inv.date.split('/').reverse().join('-'))).reduce((a, b) => a < b ? a : b).toLocaleDateString('en-GB');
    
    // CHECK FIREBASE CACHE FIRST
    const inceptionCache = (await db.ref('inceptionCache').once('value')).val() || {};
    let spyStartPrice = 0;

    if (inceptionCache.date === earliestDateStr && inceptionCache.price > 0) {
        console.log("Using cached inception price.");
        spyStartPrice = inceptionCache.price;
    } else {
        console.log("Fetching new historical price...");
        spyStartPrice = await fetchHistoricalPrice('SPY', earliestDateStr, process.env.ALPHA_VANTAGE_KEY);
        if (spyStartPrice > 0) {
            await db.ref('inceptionCache').set({ date: earliestDateStr, price: spyStartPrice });
        }
    }
    
    const benchmarkCache = { ourReturn: 0, spyReturn: 0 };
    if (totalInvested > 0 && spyStartPrice > 0) {
        benchmarkCache.ourReturn = ((totalValue - totalInvested) / totalInvested) * 100;
        benchmarkCache.spyReturn = (( (priceCache['SPY']||0) - spyStartPrice) / spyStartPrice) * 100;
    }
    await db.ref('benchmarkCache').set(benchmarkCache);
    
    process.exit(0);
  } catch (e) { console.error(e); process.exit(1); }
}

main();
