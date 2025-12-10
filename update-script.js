const admin = require('firebase-admin');
const fetch = require('node-fetch');

// --- Helper Functions ---
const fetchFinnhubPrice = async (symbol, apiKey) => {
  const url = `https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${apiKey}`;
  try {
    const res = await fetch(url);
    if (!res.ok) { console.error(`Finnhub API error for ${symbol}: ${res.status}`); return 0; }
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
                if (d["Information"] || d["Note"]) { // Check for rate limit message
                    console.warn("Alpha Vantage API limit hit or note received.");
                    return 0; // Return 0 if limit is hit
                }
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

    const investments = (await db.ref('investments').once('value')).val();
    if (!investments) { console.log("No investments found."); return admin.app().delete(); }
    
    // --- Update Live Price Cache (Fast) ---
    const finnhubApiKey = process.env.FINNHUB_API_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    const priceCache = {};
    await Promise.all(symbols.map(async (symbol) => {
        priceCache[symbol] = await fetchFinnhubPrice(symbol, finnhubApiKey);
    }));
    await db.ref('priceCache').set(priceCache);
    console.log("Updated price cache.");

    // --- Update Benchmark Cache (Smart) ---
    const earliestDate = new Date(Math.min(...Object.values(investments).map(inv => new Date(inv.date.split('/').reverse().join('-')))));
    const earliestDateStr = earliestDate.toLocaleDateString('en-GB');
    
    const inceptionCache = (await db.ref('inceptionCache').once('value')).val() || {};
    let spyStartPrice = 0;

    if (inceptionCache.date === earliestDateStr && inceptionCache.spyStartPrice > 0) {
        console.log("Using cached inception price for SPY.");
        spyStartPrice = inceptionCache.spyStartPrice;
    } else {
        console.log("Inception date changed or cache empty. Fetching new historical SPY price...");
        const alphaApiKey = process.env.ALPHA_VANTAGE_KEY;
        spyStartPrice = await fetchHistoricalPrice('SPY', earliestDateStr, alphaApiKey);
        if (spyStartPrice > 0) {
            await db.ref('inceptionCache').set({ date: earliestDateStr, spyStartPrice: spyStartPrice });
            console.log("Saved new inception data to cache.");
        }
    }
    
    // --- Final Calculation ---
    let totalInvested = 0, totalValue = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        totalValue += inv.shares * (priceCache[inv.symbol] || 0);
    });
    
    const spyCurrentPrice = priceCache['SPY'] || 0;
    const benchmarkCache = { ourReturn: 0, spyReturn: 0 };
    if (totalInvested > 0 && spyStartPrice > 0 && spyCurrentPrice > 0) {
        benchmarkCache.ourReturn = ((totalValue - totalInvested) / totalInvested) * 100;
        benchmarkCache.spyReturn = ((spyCurrentPrice - spyStartPrice) / spyStartPrice) * 100;
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
