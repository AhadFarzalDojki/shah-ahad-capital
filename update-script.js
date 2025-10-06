const admin = require('firebase-admin');
const fetch = require('node-fetch');

// --- Helper Functions ---
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const fetchWithRetry = async (url, options, retries = 3) => {
  for (let i = 0; i < retries; i++) {
    try {
      return await fetch(url, options);
    } catch (err) {
      if (i === retries - 1) throw err;
      await sleep(1000); // Wait 1 second before retrying
    }
  }
};
const fetchLivePrice = async (symbol, apiKey) => {
  const url = `https://api.api-ninjas.com/v1/stockprice?ticker=${symbol}`;
  const res = await fetchWithRetry(url, { headers: { 'X-Api-Key': apiKey } });
  if (!res.ok) return 0;
  const data = await res.json();
  return data.price || 0;
};
const fetchHistoricalPrice = async (symbol, dateStr, apiKey) => {
    let targetDate = new Date(dateStr.split('/').reverse().join('-'));
    for (let i = 0; i < 7; i++) {
        const formattedDate = targetDate.toISOString().split('T')[0];
        const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=${symbol}&apikey=${apiKey}`;
        const res = await fetchWithRetry(url);
        if(res.ok) {
            const data = await res.json();
            if (data?.["Time Series (Daily)"]?.[formattedDate]) {
                return parseFloat(data["Time Series (Daily)"][formattedDate]["4. close"]);
            }
        }
        targetDate.setDate(targetDate.getDate() - 1);
    }
    return 0;
};

// --- Main Execution ---
async function main() {
  try {
    // --- Initialize Firebase ---
    const serviceAccount = JSON.parse(Buffer.from(process.env.FIREBASE_SERVICE_ACCOUNT_BASE64, 'base64').toString('utf8'));
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.DATABASE_URL
    });
    const db = admin.database();

    // --- Fetch Investments ---
    const investments = (await db.ref('investments').once('value')).val();
    if (!investments) return console.log("No investments found.");

    // --- Update Live Price Cache ---
    const ninjaApiKey = process.env.API_NINJAS_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    const priceCache = {};
    for (const symbol of symbols) {
        priceCache[symbol] = await fetchLivePrice(symbol, ninjaApiKey);
        await sleep(200); // 200ms delay between each individual request
    }
    await db.ref('priceCache').set(priceCache);
    console.log("Updated price cache:", priceCache);

    // --- Update Benchmark Cache ---
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
    console.log("Updated benchmark cache:", benchmarkCache);

  } catch (e) {
    console.error("FATAL ERROR:", e);
    process.exit(1);
  }
}

main();
