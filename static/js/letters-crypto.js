// Device-local E2EE identity for Sinefil Mektupları. The private CryptoKey is
// non-extractable and stored only in this browser's IndexedDB; the API sees
// the public key and encrypted letter packets, never a private key or text.

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const INFO = encoder.encode('movieboxd-sinefil-mektubu-v2');
const DB_NAME = 'movieboxd-letter-identity';
const STORE = 'keys';

function toB64(bytes) {
  let binary = '';
  const data = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
  for (const byte of data) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromB64(value) {
  const raw = String(value || '');
  const padded = raw.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - raw.length % 4) % 4);
  return Uint8Array.from(atob(padded), char => char.charCodeAt(0));
}

function random(size) { return crypto.getRandomValues(new Uint8Array(size)); }

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Yerel anahtar deposu açılamadı.'));
  });
}

async function readDeviceKey(accountId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE, 'readonly').objectStore(STORE).get(String(accountId));
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error || new Error('Yerel anahtar okunamadı.'));
  });
}

async function writeDeviceKey(accountId, value) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE, 'readwrite').objectStore(STORE).put(value, String(accountId));
    request.onsuccess = () => resolve(value);
    request.onerror = () => reject(request.error || new Error('Yerel anahtar kaydedilemedi.'));
  });
}

export async function loadOrCreateDeviceIdentity(accountId) {
  const saved = await readDeviceKey(accountId);
  if (saved?.privateKey && saved?.publicKey) return saved;
  // Generate exportable once, then re-import the private key as non-extractable
  // before it is persisted. This allows IndexedDB to retain a CryptoKey without
  // ever putting private bytes in application/server storage.
  const generated = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const privateRaw = await crypto.subtle.exportKey('pkcs8', generated.privateKey);
  const privateKey = await crypto.subtle.importKey('pkcs8', privateRaw, { name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  const publicKey = await crypto.subtle.exportKey('raw', generated.publicKey);
  return writeDeviceKey(accountId, { privateKey, publicKey: toB64(publicKey), createdAt: new Date().toISOString() });
}

async function sharedAesKey(privateKey, otherPublicKeyB64, salt) {
  const other = await crypto.subtle.importKey('raw', fromB64(otherPublicKeyB64), { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const bits = await crypto.subtle.deriveBits({ name: 'ECDH', public: other }, privateKey, 256);
  const material = await crypto.subtle.importKey('raw', bits, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256', salt, info: INFO }, material, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}

export async function encryptLetter(privateKey, senderPublicKey, recipient) {
  const body = String(recipient.body || '').trim();
  if (!body || body.length > 600) throw new Error('Mektup 1–600 karakter arasında olmalı.');
  const salt = random(16); const iv = random(12);
  const key = await sharedAesKey(privateKey, recipient.public_key, salt);
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoder.encode(JSON.stringify({ v: 2, body, film: recipient.film || null })));
  return { ciphertext: toB64(ciphertext), iv: toB64(iv), salt: toB64(salt), sender_public_key: senderPublicKey, recipient_public_key: recipient.public_key };
}

export async function decryptLetter(privateKey, packet, isSender) {
  const peerKey = isSender ? packet.recipient_public_key : packet.sender_public_key;
  const key = await sharedAesKey(privateKey, peerKey, fromB64(packet.salt));
  const raw = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromB64(packet.iv) }, key, fromB64(packet.ciphertext));
  const payload = JSON.parse(decoder.decode(raw));
  if (!payload || ![1, 2].includes(payload.v) || typeof payload.body !== 'string') throw new Error('Mektup biçimi desteklenmiyor.');
  return payload;
}
