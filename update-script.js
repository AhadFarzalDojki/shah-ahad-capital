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
    
    // START: MODIFIED LOGIC
    // 1. Get the old cache first to preserve good data
    let priceCache = (await db.ref('priceCache').once('value')).val() || {};
    console.log("Loaded existing cache with", Object.keys(priceCache).length, "prices.");

    const ninjaApiKey = process.env.API_NINJAS_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    // 2. Fetch new prices
    for (const symbol of symbols) {
      const newPrice = await fetchLivePrice(symbol, ninjaApiKey);
      // 3. Only update the cache if the new price is valid (> 0)
      if (newPrice > 0) {
        priceCache[symbol] = newPrice;
        console.log(`Successfully updated ${symbol}: ${newPrice}`);
      } else {
        console.warn(`Failed to fetch valid price for ${symbol}. Keeping old price.`);
      }
      await sleep(250); // Small delay between each request
    }
    await db.ref('priceCache').set(priceCache);
    console.log("Finished updating price cache.");
    // END: MODIFIED LOGIC

    // Benchmark calculation remains the same...
    let totalInvested = 0, totalValue = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        totalValue += inv.shares * (priceCache[inv.symbol] || 0);
    });
    const earliestDateStr = Object.values(investments).map(inv => new Date(inv.date.split('/').reverse().join('-'))).reduce((a, b) => a < b ? a : b).toLocaleDateString('en-GB');
    const alphaApiKey = process.env.ALPHA_VANTAGE_KEY;
    const [d,m,y] = earliestDateStr.split('/');
    let targetDate = new Date(`${y}-${m}-${d}`);
    let spyStartPrice = 0;
    for (let i = 0; i < 7; i++) {
        const formattedDate = targetDate.toISOString().split('T')[0];
        const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=SPY&apikey=${alphaApiKey}`;
        try {
            const r = await fetch(url);
            if (r.ok) {
                const data = await r.json();
                if (data?.["Time Series (Daily)"]?.[formattedDate]) {
                    spyStartPrice = parseFloat(data["Time Series (Daily)"][formattedDate]["4. close"]);
                    break;
                }
            }
        } catch(e) { console.error(e); }
        targetDate.setDate(targetDate.getDate() - 1);
    }
    const spyCurrentPrice = priceCache['SPY'] || 0;
    const benchmarkCache = { ourReturn: 0, spyReturn: 0 };
    if (totalInvested > 0 && spyStartPrice > 0 && spyCurrentPrice > 0) {
        benchmarkCache.ourReturn = ((totalValue - totalInvested) / totalInvested) * 100;
        benchmarkCache.spyReturn = ((spyCurrentPrice - spyStartPrice) / spyStartPrice) * 100;
    }
    await db.ref('benchmarkCache').set(benchmarkCache);
    console.log("Updated benchmark cache.");

    return admin.app().delete(); // Correctly exit

  } catch (e) {
    console.error("FATAL ERROR:", e);
    if (admin.apps.length) admin.app().delete();
    process.exit(1);
  }
}

main();
