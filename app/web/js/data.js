// App-side data access layer: fetch the snapshot from the PC, cache it in
// IndexedDB, and read it back offline. The ML model never runs on the device;
// the app only consumes the pre-categorized JSON snapshot.

const SETTINGS_KEY = "gestor_settings";
const DB_NAME = "economy-db";
const DB_VERSION = 1;
const STORE = "snapshot";

// ---- settings (localStorage) ----

function getSettings() {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {};
  } catch (_) {
    return {};
  }
}

function saveSettings(settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

// ---- IndexedDB cache ----

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function cacheSnapshot(snapshot) {
  return openDb().then(
    (db) =>
      new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(snapshot, "current");
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      })
  );
}

function getCachedSnapshot() {
  return openDb().then(
    (db) =>
      new Promise((resolve) => {
        const tx = db.transaction(STORE, "readonly");
        const req = tx.objectStore(STORE).get("current");
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => resolve(null);
      })
  );
}

function clearSnapshotCache() {
  return openDb().then(
    (db) =>
      new Promise((resolve) => {
        const tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).clear();
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
      })
  );
}

// ---- sync ----

function fetchSnapshot(url, token) {
  const headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;
  return fetch(url, { headers, cache: "no-store" }).then((res) => {
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  });
}

// Fetch from the PC, store in the offline cache, bump lastSynced.
async function syncNow() {
  const settings = getSettings();
  const url = settings.snapshotUrl || DEFAULT_SNAPSHOT_URL;
  if (!url) throw new Error("No snapshot URL configured (open settings)");

  const snapshot = await fetchSnapshot(url, settings.token);
  if (!snapshot || !Array.isArray(snapshot.transactions)) {
    throw new Error("Snapshot has an unexpected shape");
  }
  await cacheSnapshot(snapshot);
  const next = getSettings();
  next.lastSynced = new Date().toISOString();
  saveSettings(next);
  return snapshot;
}
