const STORAGE_PREFIX = "tarsgo:daily-leave-public-capability:v1:"

export const PUBLIC_CAPABILITY_TTL_MS = 7 * 24 * 60 * 60 * 1000

function urlSafeRandomId(cryptoApi) {
  if (!cryptoApi?.getRandomValues) return null
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")
}

function keyPrefix(activityToken) {
  return `${STORAGE_PREFIX}${encodeURIComponent(activityToken)}:`
}

function validRecord(record, activityToken, now) {
  return Boolean(
    record &&
    record.version === 1 &&
    record.activityToken === activityToken &&
    /^[A-Za-z0-9_-]{40,50}$/.test(record.activityToken) &&
    typeof record.name === "string" &&
    record.name.trim().length >= 2 &&
    record.name.trim().length <= 50 &&
    typeof record.studentId === "string" &&
    /^[0-9]{8}$/.test(record.studentId) &&
    typeof record.college === "string" &&
    record.college.length > 0 &&
    typeof record.credential === "string" &&
    /^[A-Za-z0-9_-]{43}$/.test(record.credential) &&
    Number.isFinite(record.createdAt) &&
    Number.isFinite(record.expiresAt) &&
    record.expiresAt > now &&
    record.expiresAt > record.createdAt &&
    record.expiresAt - record.createdAt <= PUBLIC_CAPABILITY_TTL_MS,
  )
}

/**
 * Save an opaque capability in tab-scoped storage before making the POST.
 * The random storage handle is independent of the student ID, so typing an ID
 * never performs a capability lookup.
 */
export function savePublicCapability(storage, activityToken, submission, credential, cryptoApi = globalThis.crypto, now = Date.now()) {
  const id = urlSafeRandomId(cryptoApi)
  if (!storage || !id) return null

  const record = {
    version: 1,
    activityToken,
    name: submission.name,
    studentId: submission.studentId,
    college: submission.college,
    credential,
    createdAt: now,
    expiresAt: now + PUBLIC_CAPABILITY_TTL_MS,
  }
  if (!validRecord(record, activityToken, now)) return null

  const storageKey = `${keyPrefix(activityToken)}${id}`
  try {
    storage.setItem(storageKey, JSON.stringify(record))
    return { ...record, storageId: id }
  } catch {
    return null
  }
}

/** Remove malformed and expired app-owned entries, then list this activity's records. */
export function listPublicCapabilities(storage, activityToken, now = Date.now()) {
  if (!storage) return []

  try {
    const keys = []
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index)
      if (key?.startsWith(STORAGE_PREFIX)) keys.push(key)
    }

    const records = []
    for (const key of keys) {
      let record
      try {
        record = JSON.parse(storage.getItem(key) ?? "null")
      } catch {
        storage.removeItem(key)
        continue
      }

      const storedActivityToken = typeof record?.activityToken === "string" ? record.activityToken : ""
      if (!validRecord(record, storedActivityToken, now)) {
        storage.removeItem(key)
        continue
      }
      if (storedActivityToken !== activityToken) continue

      records.push({ ...record, storageId: key.slice(keyPrefix(activityToken).length) })
    }
    return records.sort((left, right) => right.createdAt - left.createdAt)
  } catch {
    return []
  }
}

export function removePublicCapability(storage, activityToken, storageId) {
  if (!storage || !/^[a-f0-9]{32}$/.test(storageId)) return
  try {
    storage.removeItem(`${keyPrefix(activityToken)}${storageId}`)
  } catch {
    // Storage can be disabled or become unavailable between reads and writes.
  }
}

export function samePublicSubmissionIdentity(left, right) {
  return Boolean(
    left &&
    right &&
    left.activityToken === right.activityToken &&
    left.name === right.name &&
    left.studentId === right.studentId &&
    left.college === right.college,
  )
}
