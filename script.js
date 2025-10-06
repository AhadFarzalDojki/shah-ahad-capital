// Firebase Config
const firebaseConfig = {
  apiKey: "AIzaSyBmCJR5WMYqve41_n9LV8P1A1bbIw-bjQ4",
  authDomain: "tracker-b57d5.firebaseapp.com",
  databaseURL: "https://tracker-b57d5-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "tracker-b57d5",
  storageBucket: "tracker-b57d5.firebasestorage.app",
  messagingSenderId: "915645082004",
  appId: "1:915645082004:web:662514ba16def0db584781",
  measurementId: "G-K32PH690Q0"
};

firebase.initializeApp(firebaseConfig);
const db = firebase.database();
const auth = firebase.auth();

let isAdmin = false;
let listenersAttached = false;

// ────────────── Auth State Listener ──────────────
auth.onAuthStateChanged(async user => {
  if (user) {
    console.log("User logged in:", user.uid, user.email);
    try {
      const snapshot = await db.ref(`roles/${user.uid}`).once("value");
      const role = snapshot.val();
      isAdmin = role === "admin";
      console.log("User role:", role, "isAdmin:", isAdmin);
      document.getElementById("userStatus").textContent = `Logged in as ${user.email}`;
      document.getElementById("adminControls").style.display = isAdmin ? "block" : "none";
      // Load investments & realized data
    } catch (error) {
      console.error("Failed to fetch user role:", error);
      isAdmin = false;
      document.getElementById("userStatus").textContent = "Logged in (role unknown)";
      document.getElementById("adminControls").style.display = "none";
    }
  } else {
    console.log("User logged out");
    isAdmin = false;
    document.getElementById("userStatus").textContent = "Not logged in";
    document.getElementById("adminControls").style.display = "none";
    clearDataDisplay();
  }

  setTimeout(renderBlogPosts, 100);
});

// ────────────── Auth Handlers ──────────────
function login() {
  const email = document.getElementById("loginEmail").value.trim();
  const password = document.getElementById("loginPass").value;

  console.log(`Attempting login with: ${email}`);

  auth.signInWithEmailAndPassword(email, password)
    .then(userCredential => {
      console.log("Login successful:", userCredential.user.email);
      alert(`Welcome, ${userCredential.user.email}!`);
    })
    .catch(error => {
      console.error("Login failed:", error.code, error.message);
      alert(`Login failed: ${error.message}`);
    });
}

function logout() {
  auth.signOut();
}

// ────────────── Clear UI Data on Logout ──────────────
function clearDataDisplay() {
  document.querySelector("#holdingsTable tbody").innerHTML = "";
  document.querySelector("#realizedTable tbody").innerHTML = "";
  document.getElementById("reasoningList").innerHTML = "";
  updateSummary(0, 0);
  updateRealizedSummary(0);
  listenersAttached = false;
}

// ────────────── Fetch Live Price ──────────────
function fetchLivePrice(symbol, callback) {
  fetch(`https://api.api-ninjas.com/v1/stockprice?ticker=${symbol}`, {
    headers: { 'X-Api-Key': 'oeiIudISb7t/OIbJwp21WA==xTFCjztakHH9mqbn' }
  })
    .then(res => res.json())
    .then(data => callback(data.price || 0))
    .catch(err => {
      console.error("Price fetch error:", err);
      callback(0);
    });
}

// ────────────── Investment Handlers ──────────────
function getInputValues() {
  return {
    symbol: document.getElementById("symbol").value.toUpperCase(),
    shares: parseFloat(document.getElementById("shares").value),
    price: parseFloat(document.getElementById("price").value),
    date: document.getElementById("date").value,
    reasoning: document.getElementById("reasoning").value
  };
}

function addInvestment() {
  if (!isAdmin) return alert("Only admins can add investments.");
  const inv = getInputValues();
  if (!inv.symbol || isNaN(inv.shares) || isNaN(inv.price) || !inv.date || !inv.reasoning) {
    return alert("Please fill out all fields correctly.");
  }
  db.ref("investments").push(inv);
  clearInputs();
}

function clearInputs() {
  ["symbol", "shares", "price", "date", "reasoning"].forEach(id => {
    document.getElementById(id).value = "";
  });
}

function clearAll() {
  if (!isAdmin) return alert("Only admins can clear data.");
  db.ref("investments").remove();
  db.ref("realized").remove();
  updateSummary(0, 0);
  updateRealizedSummary(0);
}

// ────────────── Render Holdings & Realized ──────────────
function renderData() {
  if (listenersAttached) return;
  listenersAttached = true;

  db.ref("investments").on("value", snapshot => {
    const data = snapshot.val() || {};
    const tbody = document.querySelector("#holdingsTable tbody");
    const reasoningList = document.getElementById("reasoningList");

    tbody.innerHTML = "";
    reasoningList.innerHTML = "";

    let totalInvested = 0;
    let totalValue = 0;
    let processed = 0;
    const entries = Object.entries(data);
    const totalEntries = entries.length;

    if (totalEntries === 0) {
      updateSummary(0, 0);
      return;
    }

    entries.forEach(([id, inv]) => {
      const costBasis = inv.shares * inv.price;
      totalInvested += costBasis;

      fetchLivePrice(inv.symbol, currentPrice => {
        const value = inv.shares * currentPrice;
        totalValue += value;
        const pl = value - costBasis;
        const perc = costBasis > 0 ? (pl / costBasis) * 100 : 0;

        const [d1, m1, y1] = inv.date.split("/").map(Number);
        const start = new Date(`${y1}-${m1}-${d1}`);
        const today = new Date();
        const diffTime = Math.abs(today - start);
        const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
        const months = Math.floor(diffDays / 30);
        const days = diffDays % 30;
        const duration = `${months} months, ${days} days`;

        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${inv.symbol}</td>
          <td>${inv.shares}</td>
          <td>$${inv.price.toFixed(2)}</td>
          <td>$${currentPrice.toFixed(2)}</td>
          <td>$${value.toFixed(2)}</td>
          <td class="${pl >= 0 ? 'profit' : 'loss'}">$${pl.toFixed(2)} (${perc.toFixed(1)}%)</td>
          <td>${duration}</td>
          <td>
            ${isAdmin ? `<button onclick="sellInvestment('${id}')">Sell</button>` : ""}
            ${isAdmin ? `<button onclick="deleteStock('${id}')">🗑️</button>` : ""}
          </td>
        `;
        tbody.appendChild(tr);

        processed++;
        if (processed === totalEntries) {
          updateSummary(totalInvested, totalValue);
        }
      });

      const li = document.createElement("li");
      li.textContent = `${inv.symbol} (${inv.date}): ${inv.reasoning}`;
      reasoningList.appendChild(li);
    });
  });

  db.ref("realized").on("value", snapshot => {
    const data = snapshot.val() || {};
    const tbody = document.querySelector("#realizedTable tbody");
    tbody.innerHTML = "";

    let realizedPL = 0;

    Object.values(data).forEach(item => {
      realizedPL += parseFloat(item.pl);

      const [d1, m1, y1] = item.buyDate.split("/").map(Number);
      const [d2, m2, y2] = item.sellDate.split("/").map(Number);
      const start = new Date(`${y1}-${m1}-${d1}`);
      const end = new Date(`${y2}-${m2}-${d2}`);
      const diffTime = Math.abs(end - start);
      const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
      const months = Math.floor(diffDays / 30);
      const days = diffDays % 30;
      const duration = `${months} months, ${days} days`;

      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${item.symbol}</td>
        <td>${item.shares}</td>
        <td>$${item.buyPrice.toFixed(2)}</td>
        <td>$${item.sellPrice.toFixed(2)}</td>
        <td>${item.buyDate}</td>
        <td>${item.sellDate}</td>
        <td>${duration}</td>
        <td class="${item.pl >= 0 ? 'profit' : 'loss'}">$${item.pl.toFixed(2)}</td>
      `;
      tbody.appendChild(row);
    });

    updateRealizedSummary(realizedPL);
  });
}

function deleteStock(id) {
  if (!isAdmin) return alert("Only admins can delete stocks.");
  if (!confirm("Are you sure you want to delete this stock? This cannot be undone.")) return;
  db.ref(`investments/${id}`).remove()
    .then(() => {
      alert("Stock deleted.");
    })
    .catch(err => {
      console.error("Delete failed:", err);
      alert("Failed to delete. Check console for details.");
    });
}

function updateSummary(invested, value) {
  const pl = value - invested;
  const perc = invested > 0 ? (pl / invested) * 100 : 0;

  document.getElementById("totalInvested").textContent = `$${invested.toFixed(2)}`;
  document.getElementById("totalValue").textContent = `$${value.toFixed(2)}`;
  const el = document.getElementById("unrealizedPL");
  el.textContent = `$${pl.toFixed(2)} (${perc.toFixed(1)}%)`;
  el.className = pl >= 0 ? 'profit' : 'loss';
}

function updateRealizedSummary(realizedPL) {
  const el = document.getElementById("realizedPL");
  el.textContent = `$${realizedPL.toFixed(2)}`;
  el.className = realizedPL >= 0 ? 'profit' : 'loss';
}

function sellInvestment(id) {
  if (!isAdmin) return alert("Only admins can sell stocks.");
  
  db.ref(`investments/${id}`).once("value", snapshot => {
    const inv = snapshot.val();
    if (!inv) return;

    const sellPriceInput = prompt(`Enter sell price per share for ${inv.symbol}:`, inv.price);
    const sellPrice = parseFloat(sellPriceInput);
    if (isNaN(sellPrice)) return alert("Invalid sell price.");

    const sellDateInput = prompt("Enter sell date (dd/mm/yyyy):", new Date().toLocaleDateString("en-GB"));
    
    // Calculate P/L
    const pl = (sellPrice - inv.price) * inv.shares;

    // Extract day, month, year
    const [day, month, year] = sellDateInput.split("/").map(num => parseInt(num, 10));

    // Determine quarter
    let quarter;
    if (month >= 1 && month <= 3) quarter = "Q1";
    else if (month >= 4 && month <= 6) quarter = "Q2";
    else if (month >= 7 && month <= 9) quarter = "Q3";
    else quarter = "Q4";

    // Path: archivedTrades/<year>/<quarter>
    const archivePath = `archivedTrades/${year}/${quarter}`;

    // Push to the correct archive location
    db.ref(archivePath).push({
      symbol: inv.symbol,
      shares: inv.shares,
      buyPrice: inv.price,
      sellPrice: sellPrice,
      buyDate: inv.date,
      sellDate: sellDateInput,
      pl: pl
    });

    // Remove from active investments
    db.ref(`investments/${id}`).remove();

    alert(`Trade archived to ${archivePath}`);
  });
}

// ────────────── Blog Logic ──────────────
// ... Keep your existing blog logic unchanged

