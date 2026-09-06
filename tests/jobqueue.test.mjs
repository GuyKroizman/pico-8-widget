// Node tests for JobQueue.js (pure JS, no Qt). Run with:
//   node --test tests/jobqueue.test.mjs
// Loaded via vm so the same file works as a QML import and in Node.

import { readFileSync } from "node:fs"
import test from "node:test"
// Loose assertions: queue/parse results are created inside the vm sandbox
// realm, and strict deepEqual compares prototypes across realms.
import assert from "node:assert"
import vm from "node:vm"

const source = readFileSync(new URL("../JobQueue.js", import.meta.url), "utf8")
const sandbox = { JSON } // host JSON so parsed objects live in this realm
vm.createContext(sandbox)
vm.runInContext(source, sandbox)
const { createJobQueue, parseHelperOutput } = sandbox

test("parseHelperOutput finds the last JSON line", () => {
  const first = parseHelperOutput('warning line\n{"ok":true,"x":1}')
  assert.deepEqual(first, { ok: true, x: 1 })
  const last = parseHelperOutput('junk\n{"ok":true}\n{"ok":false,"error":"x"}')
  assert.deepEqual(last, { ok: false, error: "x" })
  assert.equal(parseHelperOutput("no json here"), null)
  assert.equal(parseHelperOutput(""), null)
})

test("enqueues and starts the first job immediately", () => {
  const q = createJobQueue()
  const d1 = q.enqueue(["a"], () => {})
  assert.equal(d1.start, true)
  assert.deepEqual(d1.command, ["a"])
  // second job waits
  assert.equal(q.enqueue(["b"], () => {}).start, false)
  assert.equal(q.enqueue(["c"], () => {}).start, false)
})

test("jobs run FIFO, one at a time", () => {
  const q = createJobQueue()
  const order = []
  q.enqueue(["a"], () => order.push("a"))
  q.enqueue(["b"], () => order.push("b"))
  q.enqueue(["c"], () => order.push("c"))

  let d = q.finishWith({ ok: true })
  assert.equal(d.start, true)
  assert.deepEqual(d.command, ["b"])
  d = q.finishWith({ ok: true })
  assert.deepEqual(d.command, ["c"])
  d = q.finishWith({ ok: true })
  assert.equal(d.start, false)
  assert.deepEqual(order, ["a", "b", "c"])
})

test("non-zero exit finishes with an error", () => {
  const q = createJobQueue()
  const results = []
  q.enqueue(["run"], (r) => results.push(r))
  const d = q.onExit(3)
  assert.deepEqual(d, { finish: { ok: false, error: "helper exited 3" } })
})

test("REG: exit 0 before output is delivered is NOT a failure", () => {
  // This is the bug that made bookmarks silently fail: Quickshell fires
  // onExited before onStreamFinished, and finishing on exit-0 reported a
  // successful run as "helper exited 0".
  const q = createJobQueue()
  const results = []
  q.enqueue(["pick"], (r) => results.push(r))

  const d = q.onExit(0) // exit arrives FIRST
  assert.deepEqual(d, { waitForOutput: true }) // must not finish

  const out = q.onOutput('{"ok":true,"tid":42}')
  assert.deepEqual(out, { finish: { ok: true, tid: 42 } })
  q.finishWith(out.finish) // QML applies the decision via finishWith
  assert.deepEqual(results, [{ ok: true, tid: 42 }])
})

test("output before exit 0 also finishes exactly once", () => {
  const q = createJobQueue()
  const results = []
  q.enqueue(["pick"], (r) => results.push(r))

  const out = q.onOutput('{"ok":true}')
  assert.deepEqual(out.finish, { ok: true })
  q.finishWith(out.finish)
  // late signals after the job finished are ignored
  assert.equal(q.onExit(0), null)
  assert.equal(q.onOutput("more"), null)
  assert.deepEqual(results, [{ ok: true }])
})

test("exit 0 with no output fails after the grace period", () => {
  const q = createJobQueue()
  const results = []
  q.enqueue(["pick"], (r) => results.push(r))
  assert.deepEqual(q.onExit(0), { waitForOutput: true })
  const g = q.onOutputGrace()
  assert.deepEqual(g, { finish: { ok: false, error: "helper produced no output" } })
  q.finishWith(g.finish)
  assert.deepEqual(results, [{ ok: false, error: "helper produced no output" }])
})

test("watchdog kill is a timeout, natural stop is not", () => {
  const q = createJobQueue()
  const results = []
  q.enqueue(["pick"], (r) => results.push(r))

  // natural stop before any exit signal: wait for output, do not fail
  assert.deepEqual(q.onStopped(), { waitForOutput: true })

  // watchdog path
  assert.deepEqual(q.onWatchdogFire(), { kill: true })
  const t = q.onStopped()
  assert.deepEqual(t, { finish: { ok: false, error: "helper timed out" } })
  q.finishWith(t.finish)
  assert.deepEqual(results, [{ ok: false, error: "helper timed out" }])
})

test("watchdog that fires after output finished is ignored", () => {
  const q = createJobQueue()
  const results = []
  q.enqueue(["pick"], (r) => results.push(r))
  const out = q.onOutput('{"ok":true}')
  q.finishWith(out.finish)
  assert.equal(q.onWatchdogFire(), null)
  assert.equal(q.onStopped(), null)
  assert.deepEqual(results, [{ ok: true }])
})

test("unreadable output finishes with an error", () => {
  const q = createJobQueue()
  const results = []
  q.enqueue(["run"], (r) => results.push(r))
  const d = q.onOutput("completely broken output")
  assert.deepEqual(d, { finish: { ok: false, error: "unreadable helper output" } })
  q.finishWith(d.finish)
  assert.deepEqual(results, [{ ok: false, error: "unreadable helper output" }])
})
