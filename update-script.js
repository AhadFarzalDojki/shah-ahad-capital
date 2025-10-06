const admin = require('firebase-admin');
const fetch = require('node-fetch');

try {
  // Decode the service account key from Base64
  const serviceAccount_base64 = process.env.FIREBASE_SERVICE_ACCOUNT_BASE64;
  if (!serviceAccount_base64) {
    throw new Error("FIREBASE_SERVICE_ACCOUNT_BASE64 secret is not set.");
  }
  const serviceAccount_json = Buffer.from(serviceAccount_base64, 'base64').toString('utf8');
  const serviceAccount = JSON.parse(serviceAccount_json);

  const databaseURL = process.env.DATABASE_URL;
  const apiKey = process.env.API_NINJAS_KEY;

  if (!databaseURL || !apiKey) {
    throw new Error("DATABASE_URL or API_NINJAS_KEY is not set.");
  }

  admin.initializeApp({
    credential: admin.credential.cert(serviceAccount),
    databaseURL: databaseURL
  });

  const db = admin.database();

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  async function fetchLivePrice(symbol) {
    try {
      const response = await fetch(`https://api.api-ninjas.com/v1/stockprice?ticker=${symbol}`, {
        headers: { 'X-Api-Key': apiKey }
      });
      if (!response.ok) return 0;
      const data = await response.json();
      return data.price || 0;
    } catch (error) {
      console.error(`Error fetching price for ${symbol}:`, error);
      return 0;
    }
  }

  async function updateAllPrices() {
    console.log("Starting price update job...");
    const investments = (await db.ref('investments').once('value')).val();

    if (!investments) {
      console.log("No investments found. Exiting.");
      process.exit(0);
    }

    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    const priceCache = {};

    const batchSize = 5;
    for (let i = 0; i < symbols.length; i += batchSize) {
      const batch = symbols.slice(i, i + batchSize);
      await Promise.all(batch.map(async (symbol) => {
        const price = await fetchLivePrice(symbol);
        if (price > 0) {
          priceCache[symbol] = price;
          console.log(`Fetched ${symbol}: ${price}`);
        }
      }));
      if (i + batchSize < symbols.length) await sleep(1000);
    }

    if (Object.keys(priceCache).length > 0) {
      await db.ref('priceCache').set(priceCache);
      console.log("Successfully updated price cache in Firebase.");
    } else {
      console.log("No prices were fetched.");
    }
    process.exit(0);
  }

  updateAllPrices();

} catch (e) {
  console.error("FATAL ERROR:", e.message);
  process.exit(1);
}
