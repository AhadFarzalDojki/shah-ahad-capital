// firebase-init.js — modular Firebase v10 style

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
import { getDatabase } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-database.js";

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

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getDatabase(app);
