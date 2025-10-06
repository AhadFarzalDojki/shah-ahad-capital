const admin = require('firebase-admin');
const fetch = require('node-fetch');

const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT);
const databaseURL = process.env.DATABASE_URL;
const apiKey = process.env.API_NINJAS_KEY;

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
  const investmentsRef = db.ref('investments');
  const snapshot = await investmentsRef.once('value');
  const investments = snapshot.val();

  if (!investments) {
    console.log("No investments found. Exiting.");
    return;
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
    if (i + batchSize < symbols.length) {
      await sleep(1000); // 1-second delay between batches
    }
  }

  if (Object.keys(priceCache).length > 0) {
    await db.ref('priceCache').set(priceCache);
    console.log("Successfully updated price cache in Firebase.");
  } else {
    console.log("No prices were fetched. Cache not updated.");
  }
  process.exit(0);
}

updateAllPrices();
