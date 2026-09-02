// Sinefil Mektupları crypto boundary. This module deliberately has no network
// code: lock passwords, recovery codes and decrypted private keys never leave
// the browser. Packets are ECDH P-256 + HKDF-SHA-256 + AES-256-GCM.

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const LOCK_ITERATIONS = 310000;
const INFO = encoder.encode('movieboxd-sinefil-mektubu-v1');

function toB64(bytes) {
  let binary = '';
  const data = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
  for (const byte of data) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromB64(value) {
  const padded = String(value || '').replace(/-/g, '+').replace(/_/g, '/')
    + '='.repeat((4 - String(value || '').length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, char => char.charCodeAt(0));
}

function random(size) { return crypto.getRandomValues(new Uint8Array(size)); }

async function passwordKey(secret, salt, iterations = LOCK_ITERATIONS) {
  const material = await crypto.subtle.importKey('raw', encoder.encode(secret), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations }, material, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}

async function wrapPrivate(privateKey, secret) {
  const salt = random(16);
  const iv = random(12);
  const key = await passwordKey(secret, salt);
  const raw = await crypto.subtle.exportKey('pkcs8', privateKey);
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, raw);
  return { v: 1, alg: 'PBKDF2-SHA-256/AES-256-GCM', iterations: LOCK_ITERATIONS, salt: toB64(salt), iv: toB64(iv), ciphertext: toB64(ciphertext) };
}

async function unwrapPrivate(envelope, secret) {
  if (!envelope || envelope.v !== 1 || !envelope.salt || !envelope.iv || !envelope.ciphertext) throw new Error('Mektup anahtarı bulunamadı.');
  const key = await passwordKey(secret, fromB64(envelope.salt), Number(envelope.iterations) || LOCK_ITERATIONS);
  const raw = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromB64(envelope.iv) }, key, fromB64(envelope.ciphertext));
  return crypto.subtle.importKey('pkcs8', raw, { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
}

function recoveryCode() {
  // A human-copyable 128-bit secret; format makes transcription less error-prone.
  return [...random(16)].map(n => n.toString(16).padStart(2, '0')).join('').match(/.{1,4}/g).join('-').toUpperCase();
}

export async function createLetterIdentity(lockPassword) {
  if (String(lockPassword || '').length < 10) throw new Error('Mektup kilit parolası en az 10 karakter olmalı.');
  const pair = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const recovery = recoveryCode();
  return {
    keyPair: pair,
    recovery,
    payload: {
      public_key: toB64(await crypto.subtle.exportKey('raw', pair.publicKey)),
      encrypted_private_key: await wrapPrivate(pair.privateKey, lockPassword),
      recovery_private_key: await wrapPrivate(pair.privateKey, recovery),
    },
  };
}

export async function unlockLetterIdentity(material, lockPassword) {
  const privateKey = await unwrapPrivate(material?.encrypted_private_key, lockPassword);
  return { privateKey, publicKey: await crypto.subtle.importKey('raw', fromB64(material.public_key), { name: 'ECDH', namedCurve: 'P-256' }, true, []) };
}

export async function recoverLetterIdentity(material, recovery, newLockPassword) {
  if (String(newLockPassword || '').length < 10) throw new Error('Yeni mektup kilit parolası en az 10 karakter olmalı.');
  const privateKey = await unwrapPrivate(material?.recovery_private_key, recovery);
  return { privateKey, encrypted_private_key: await wrapPrivate(privateKey, newLockPassword) };
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
  const salt = random(16);
  const iv = random(12);
  const key = await sharedAesKey(privateKey, recipient.public_key, salt);
  const payload = JSON.stringify({ v: 1, body, film: recipient.film || null });
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoder.encode(payload));
  return { ciphertext: toB64(ciphertext), iv: toB64(iv), salt: toB64(salt), sender_public_key: senderPublicKey, recipient_public_key: recipient.public_key };
}

export async function decryptLetter(privateKey, packet, isSender) {
  const peerKey = isSender ? packet.recipient_public_key : packet.sender_public_key;
  const key = await sharedAesKey(privateKey, peerKey, fromB64(packet.salt));
  const raw = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromB64(packet.iv) }, key, fromB64(packet.ciphertext));
  const payload = JSON.parse(decoder.decode(raw));
  if (!payload || payload.v !== 1 || typeof payload.body !== 'string') throw new Error('Mektup biçimi desteklenmiyor.');
  return payload;
}
