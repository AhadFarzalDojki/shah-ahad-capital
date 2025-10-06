const admin = require('firebase-admin');
const fetch = require('node-fetch');

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
      process.exit(0);
    }

    const ninjaApiKey = process.env.API_NINJAS_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    const priceCache = {};
    for (const symbol of symbols) {
      try {
        const r = await fetch(`https://api.api-ninjas.com/v1/stockprice?ticker=${symbol}`, { headers: { 'X-Api-Key': ninjaApiKey } });
        if (r.ok) {
          const d = await r.json();
          if (d.price) {
            priceCache[symbol] = d.price;
            console.log(`Fetched ${symbol}: ${d.price}`);
          }
        }
      } catch (e) { console.error(`Failed to fetch ${symbol}`, e); }
      await new Promise(resolve => setTimeout(resolve, 250)); // 250ms delay
    }
    await db.ref('priceCache').set(priceCache);
    console.log("Updated price cache.");

    // Benchmark calculation... (condensed for clarity)
    let totalInvested = 0, totalValue = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        totalValue += inv.shares * (priceCache[inv.symbol] || 0);
    });
    const earliestDateStr = Object.values(investments).map(inv => new Date(inv.date.split('/').reverse().join('-'))).reduce((a, b) => a < b ? a : b).toLocaleDateString('en-GB');
    const alphaApiKey = process.env.ALPHA_VANTAGE_KEY;
    let spyStartPrice = 0;
    let targetDate = new Date(earliestDateStr.split('/').reverse().join('-'));
    for (let i = 0; i < 7; i++) {
        const formattedDate = targetDate.toISOString().split('T')[0];
        const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=SPY&apikey=${alphaApiKey}`;
        const r = await fetch(url);
        if(r.ok) {
            const d = await r.json();
            if (d?.["Time Series (Daily)"]?.[formattedDate]) {
                spyStartPrice = parseFloat(d["Time Series (Daily)"][formattedDate]["4. close"]);
                break;
            }
        }
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

    process.exit(0);

  } catch (e) {
    console.error("FATAL ERROR:", e);
    process.exit(1);
  }
}

main();
