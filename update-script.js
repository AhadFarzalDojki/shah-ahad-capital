const admin = require('firebase-admin');
const fetch = require('node-fetch');

// --- Helper Functions ---
const fetchFinnhubPrice = async (symbol, apiKey) => {
  const url = `https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${apiKey}`;
  try {
    const res = await fetch(url);
    if (!res.ok) return 0;
    const data = await res.json();
    return data.c || 0;
  } catch (e) { return 0; }
};

async function main() {
  try {
    const serviceAccount = JSON.parse(Buffer.from(process.env.FIREBASE_SERVICE_ACCOUNT_BASE64, 'base64').toString('utf8'));
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.DATABASE_URL
    });
    const db = admin.database();

    // 1. Fetch All Data
    const [invSnap, realSnap, cacheSnap] = await Promise.all([
        db.ref('investments').once('value'),
        db.ref('realized').once('value'),
        db.ref('inceptionCache').once('value')
    ]);

    const investments = invSnap.val() || {};
    const realized = realSnap.val() || {};
    const inceptionCache = cacheSnap.val() || {};

    if (Object.keys(investments).length === 0) { console.log("No investments."); return admin.app().delete(); }
    
    // 2. Update Live Prices (Finnhub)
    const finnhubApiKey = process.env.FINNHUB_API_KEY;
    const symbols = [...new Set(Object.values(investments).map(inv => inv.symbol))];
    if (!symbols.includes('SPY')) symbols.push('SPY');
    
    const priceCache = {};
    await Promise.all(symbols.map(async (symbol) => {
        const p = await fetchFinnhubPrice(symbol, finnhubApiKey);
        if(p > 0) priceCache[symbol] = p;
    }));
    await db.ref('priceCache').set(priceCache);
    console.log("Updated prices.");

    // 3. Calculate Portfolio Totals
    let totalInvested = 0, currentVal = 0;
    Object.values(investments).forEach(inv => {
        totalInvested += inv.shares * inv.price;
        currentVal += inv.shares * (priceCache[inv.symbol] || 0);
    });
    
    // Calculate Realized P/L from history
    const totalRealizedPL = Object.values(realized).reduce((sum, trade) => sum + (trade.pl || 0), 0);
    const currentUnrealizedPL = currentVal - totalInvested;
    const allTimeTotalPL = totalRealizedPL + currentUnrealizedPL;

    // 4. Benchmark Calculations
    // Note: We use the manual cache keys we uploaded: "05-10-2025" and "14-07-2025"
    
    // A. Current Strategy (Since Oct 5)
    const currentStartKey = "05-10-2025";
    const spyCurrentStart = inceptionCache[currentStartKey] || 0;
    
    // B. All Time (Since July 14)
    const allTimeStartKey = "14-07-2025";
    const spyAllTimeStart = inceptionCache[allTimeStartKey] || 0;
    
    const spyCurrentPrice = priceCache['SPY'] || 0;

    con
