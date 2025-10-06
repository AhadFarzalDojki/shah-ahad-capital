const admin = require('firebase-admin');
const fetch = require('node-fetch');

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function fetchLivePrice(symbol, apiKey) {
  try {
    const r = await fetch(`https://api.api-ninjas.com/v1/stockprice?ticker=${symbol}`, { headers: { 'X-Api-Key': apiKey } });
    if (!r.ok) return 0;
    const d = await r.json();
    return d.price || 0;
  } catch { return 0; }
}

async function fetchHistoricalPrice(symbol, dateStr, apiKey) {
    let targetDate = new Date(dateStr.split('/').reverse().join('-'));
    for (let i = 0; i < 7; i++) {
        const formattedDate = targetDate.toISOString().split('T')[0];
        const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=${symbol}&apikey=${apiKey}`;
        try {
            const r = await fetch(url);
            if(r.ok) {
                const d = await r.json();
                if (d?.["Time Series (Daily)"]?.[formattedDate]) {
                    return parseFloat(d["Time Series (Daily)"][formattedDate]["4. close"]);
                }
            }
        } catch (error) { console.error(error); }
        targetDate.setDate(targetDate.getDate() - 1);
    }
    return 0;
}

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
        return db.app().delete(); // Correctly exit
    }

    const ninjaApiKey = process.env.API_NINJAS_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    const priceCache = {};
    for (const symbol of symbols) {
        priceCache[symbol] = await fetchLivePrice(symbol, ninjaApiKey);
        await sleep(250); // Small delay to be safe
    }
    await db.ref('priceCache').set(priceCache);
    console.log("Updated price cache:", Object.keys(priceCache).length, "symbols");

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

    return db.app().delete(); // Correctly exit after success

  } catch (e) {
    console.error("FATAL ERROR:", e);
    // Even if there's an error, try to exit cleanly
    if (admin.apps.length) {
        admin.app().delete();
    }
    process.exit(1);
  }
}

main();
