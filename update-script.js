const admin = require('firebase-admin');
const fetch = require('node-fetch');

// --- Helper Functions ---
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function fetchFinnhubPrice(symbol, apiKey) {
  const url = `https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${apiKey}`;
  try {
    const res = await fetch(url);
    if (!res.ok) { console.error(`Finnhub API error for ${symbol}: ${res.status}`); return 0; }
    const data = await res.json();
    return data.c || 0;
  } catch (e) { console.error(`Failed to fetch ${symbol} from Finnhub`, e); return 0; }
}

// --- START: NEW, SMARTER HISTORICAL FUNCTION ---
async function fetchHistoricalPrice(symbol, dateStr, apiKey) {
    let targetDate = new Date(dateStr.split('/').reverse().join('-'));
    // Look back up to 7 days to find the first available trading day
    for (let i = 0; i < 7; i++) {
        const formattedDate = targetDate.toISOString().split('T')[0]; // YYYY-MM-DD format
        const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=${symbol}&apikey=${apiKey}`;
        try {
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                if (data["Time Series (Daily)"] && data["Time Series (Daily)"][formattedDate]) {
                    console.log(`Found historical price for ${symbol} on ${formattedDate}`);
                    return parseFloat(data["Time Series (Daily)"][formattedDate]["4. close"]);
                }
            }
        } catch (error) { console.error(error); }
        // If not found, try the previous day
        targetDate.setDate(targetDate.getDate() - 1);
    }
    console.error(`Could not find any historical price for ${symbol} near ${dateStr}`);
    return 0; // Return 0 if no data is found after a week
}
// --- END: NEW, SMARTER HISTORICAL FUNCTION ---

async function main() {
  try {
    const serviceAccount = JSON.parse(Buffer.from(process.env.FIREBASE_SERVICE_ACCOUNT_BASE64, 'base64').toString('utf8'));
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.DATABASE_URL
    });
    const db = admin.database();

    const investments = (await db.ref('investments').once('value')).val();
    if (!investments) {
      console.log("No investments found.");
      return admin.app().delete();
    }
    
    let priceCache = (await db.ref('priceCache').once('value')).val() || {};
    const finnhubApiKey = process.env.FINNHUB_API_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    await Promise.all(symbols.map(async (symbol) => {
        const newPrice = await fetchFinnhubPrice(symbol, finnhubApiKey);
        if (newPrice > 0) {
            priceCache[symbol] = newPrice;
        } else {
            console.warn(`Failed to fetch valid price for ${symbol}. Keeping old price.`);
        }
    }));
    
    await db.ref('priceCache').set(priceCache);
    console.log("Finished updating price cache.");

    // Benchmark calculation...
    let totalInvested = 0, totalValue = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        totalValue += inv.shares * (priceCache[inv.symbol] || 0);
    });
    const earliestDateStr = Object.values(investments).map(inv => new Date(inv.date.split('/').reverse().join('-'))).reduce((a, b) => a < b ? a : b).toLocaleDateString('en-GB');
    const alphaApiKey = process.env.ALPHA_VANTAGE_KEY;
    const spyStartPrice = await fetchHistoricalPrice('SPY', earliestDateStr, alphaApiKey);
    const spyCurrentPrice = priceCache['SPY'] || 0;
    const benchmarkCache = { ourReturn: 0, spyReturn: 0 };
    if (totalInvested > 0 && spyStartPrice > 0 && spyCurrentPrice > 0) {
        benchmarkCache.ourReturn = ((totalValue - totalInvested) / totalInvested) * 100;
        benchmarkCache.spyReturn = ((spyCurrentPrice - spyStartPrice) / spyStartPrice) * 100;
    }
    await db.ref('benchmarkCache').set(benchmarkCache);
    console.log("Updated benchmark cache.");

    return admin.app().delete();

  } catch (e) {
    console.error("FATAL ERROR:", e);
    if (admin.apps.length) admin.app().delete();
    process.exit(1);
  }
}

main();
