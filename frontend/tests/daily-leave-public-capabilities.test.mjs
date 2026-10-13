import assert from "node:assert/strict"

import {
  listPublicCapabilities,
  PUBLIC_CAPABILITY_TTL_MS,
  removePublicCapability,
  samePublicSubmissionIdentity,
  savePublicCapability,
} from "../src/dailyLeavePublicCapabilities.js"

class MemorySessionStorage {
  values = new Map()

  get length() {
    return this.values.size
  }

  key(index) {
    return [...this.values.keys()][index] ?? null
  }

  getItem(key) {
    return this.values.get(key) ?? null
  }

  setItem(key, value) {
    this.values.set(key, String(value))
  }

  removeItem(key) {
    this.values.delete(key)
  }
}

function deterministicCrypto(seed = 1) {
  let value = seed
  return {
    getRandomValues(bytes) {
      for (let index = 0; index < bytes.length; index += 1) bytes[index] = value++ & 0xff
      return bytes
    },
  }
}

const activityToken = "A".repeat(43)
const submission = {
  name: "测试成员甲",
  studentId: "26000203",
  college: "computer-science-technology",
}
const credential = "A".repeat(43)
const now = 1_800_000_000_000
const storage = new MemorySessionStorage()

const saved = savePublicCapability(storage, activityToken, submission, credential, deterministicCrypto(), now)
assert.ok(saved, "the bearer capability is stored before submitting the request")
assert.equal(saved.expiresAt, now + PUBLIC_CAPABILITY_TTL_MS)
assert.equal(saved.expiresAt - saved.createdAt, 7 * 24 * 60 * 60 * 1000)
assert.equal(storage.length, 1)
assert.doesNotMatch(storage.key(0), /26000203/, "the storage key is random and never indexed by student ID")

// A page reload has no component memory; the same-tab session record is explicit recovery state.
const afterRefresh = listPublicCapabilities(storage, activityToken, now + 1)
assert.equal(afterRefresh.length, 1)
assert.equal(afterRefresh[0].credential, credential)
assert.equal(afterRefresh[0].studentId, submission.studentId)
assert.equal(afterRefresh[0].activityToken, activityToken)
assert.deepEqual(listPublicCapabilities(storage, "B".repeat(43), now + 1), [])

// Persisting a second identity does not overwrite the first or create an ID-based retrieval path.
const second = savePublicCapability(
  storage,
  activityToken,
  { ...submission, name: "测试成员乙", studentId: "26000204" },
  "B".repeat(43),
  deterministicCrypto(30),
  now + 2,
)
assert.ok(second)
assert.equal(listPublicCapabilities(storage, activityToken, now + 3).length, 2)

const originalIdentity = { activityToken, name: submission.name, studentId: submission.studentId, college: submission.college }
assert.equal(samePublicSubmissionIdentity(originalIdentity, { ...originalIdentity }), true)
for (const changed of [
  { ...originalIdentity, activityToken: "other-event" },
  { ...originalIdentity, name: "其他姓名" },
  { ...originalIdentity, studentId: "26000204" },
  { ...originalIdentity, college: "art" },
]) {
  assert.equal(samePublicSubmissionIdentity(originalIdentity, changed), false)
}

assert.equal(listPublicCapabilities(storage, activityToken, now + PUBLIC_CAPABILITY_TTL_MS + 3).length, 0)
assert.equal(storage.length, 0, "expired records are removed during the next list/cleanup")

const removable = savePublicCapability(storage, activityToken, submission, credential, deterministicCrypto(80), now)
removePublicCapability(storage, activityToken, removable.storageId)
assert.equal(storage.length, 0)

const unavailableStorage = {
  get length() { throw new Error("storage disabled") },
  setItem() { throw new Error("storage disabled") },
}
assert.equal(savePublicCapability(unavailableStorage, activityToken, submission, credential, deterministicCrypto(), now), null)
assert.deepEqual(listPublicCapabilities(unavailableStorage, activityToken, now), [])

console.log("daily leave public capability tests passed")
