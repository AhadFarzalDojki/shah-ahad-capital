const admin = require('firebase-admin');
const fetch = require('node-fetch');

// --- Helper Functions ---
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function fetchAlphaVantagePrice(symbol, apiKey) {
  const url = `https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=${symbol}&apikey=${apiKey}`;
  try {
    const res = await fetch(url);
    if (!res.ok) {
      console.error(`Alpha Vantage API error for ${symbol}: ${res.status}`);
      return 0;
    }
    const data = await res.json();
    // The free tier has a limit of 25 requests per day. The API returns a note when the limit is hit.
    if (data.Note && data.Note.includes('API call frequency')) {
        console.warn(`Alpha Vantage API limit reached for ${symbol}.`);
        return 0;
    }
    if (data["Global Quote"] && data["Global Quote"]["05. price"]) {
      return parseFloat(data["Global Quote"]["05. price"]);
    }
    console.warn(`Could not parse price for ${symbol} from Alpha Vantage response.`);
    return 0;
  } catch (e) {
    console.error(`Failed to fetch ${symbol} from Alpha Vantage`, e);
    return 0;
  }
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
    
    let priceCache = (await db.ref('priceCache').once('value')).val() || {};
    console.log("Loaded existing cache with", Object.keys(priceCache).length, "prices.");

    const alphaApiKey = process.env.ALPHA_VANTAGE_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    for (const symbol of symbols) {
      const newPrice = await fetchAlphaVantagePrice(symbol, alphaApiKey);
      if (newPrice > 0) {
        priceCache[symbol] = newPrice;
        console.log(`Successfully updated ${symbol}: ${newPrice}`);
      } else {
        console.warn(`Failed to fetch valid price for ${symbol}. Keeping old price.`);
      }
      // Alpha Vantage free tier is limited. We need a long delay.
      await sleep(15000); // Wait 15 seconds between each request
    }
    await db.ref('priceCache').set(priceCache);
    console.log("Finished updating price cache.");

    // Benchmark calculation remains the same
    // ... (rest of the script is unchanged)

    return admin.app().delete();

  } catch (e) {
    console.error("FATAL ERROR:", e);
    if (admin.apps.length) admin.app().delete();
    process.exit(1);
  }
}

main();
