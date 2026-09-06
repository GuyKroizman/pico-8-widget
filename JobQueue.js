// JobQueue.js - serialized command queue for Pico8Games.qml
//
// Pico8Games.qml talks to p8.py through ONE Quickshell Process (Quickshell
// can only run one command at a time). This file owns the queueing and the
// interpretation of process end-states; the QML file only performs side
// effects (starting the Process, stopping timers).
//
// The tricky part lives here on purpose: when a process ends, Quickshell
// fires onExited, onRunningChanged and the stdout collector's
// onStreamFinished in NO guaranteed order. A helper that exits 0 and then
// delivers parsed output must NEVER be reported as a failure, no matter how
// the signals interleave. That rule is what the unit tests in
// tests/jobqueue.test.mjs lock down.
//
// This file is plain JavaScript with no Qt dependencies, so it can be loaded
// both as a QML import ("JobQueue.js") and inside Node for testing.

function parseHelperOutput(text) {
  // p8.py prints exactly one JSON object on stdout; take the last
  // brace-initialized line so stray warnings above it are harmless.
  var lines = String(text || "").split("\n")
  for (var i = lines.length - 1; i >= 0; i--) {
    var line = lines[i].trim()
    if (line.charAt(0) === "{") {
      try { return JSON.parse(line) } catch (e) { return null }
    }
  }
  return null
}

function createJobQueue(parseOutput) {
  var parse = parseOutput || parseHelperOutput

  var jobs = []       // queued jobs: { args, done }
  var current = null  // the running job, if any
  var handled = true  // true once the current job's callback has been invoked
  var killed = false  // true only when the watchdog terminated the process

  return {
    // Add a job. When the queue is idle this also claims the slot and returns
    // { start: true, command } so the caller can launch the process.
    enqueue: function(args, done) {
      if (current === null) {
        current = { args: args, done: done }
        handled = false
        killed = false
        return { start: true, command: args }
      }
      jobs.push({ args: args, done: done })
      return { start: false }
    },

    // Called when the stdout collector delivers output for the running job.
    onOutput: function(text) {
      if (handled || current === null) return null
      var result = parse(text)
      return { finish: result || { ok: false, error: "unreadable helper output" } }
    },

    // Called when the process reports an exit code. Exit 0 is NOT a finish:
    // the collector may still deliver the parsed output, and finishing early
    // would report a successful run as a failure.
    onExit: function(exitCode) {
      if (handled || current === null) return null
      if (exitCode !== 0) return { finish: { ok: false, error: "helper exited " + exitCode } }
      return { waitForOutput: true }
    },

    // Called when the watchdog fires while the process is running.
    onWatchdogFire: function() {
      if (current === null) return null
      killed = true
      return { kill: true }
    },

    // Called when the process reports that it is no longer running.
    // A stop after a watchdog kill is a timeout; a natural stop is not a
    // finish by itself (see onExit / onOutput).
    onStopped: function() {
      if (handled || current === null) return null
      if (killed) return { finish: { ok: false, error: "helper timed out" } }
      return { waitForOutput: true }
    },

    // Called if exit-0 output never arrives (grace timer expired).
    onOutputGrace: function() {
      if (handled || current === null) return null
      return { finish: { ok: false, error: "helper produced no output" } }
    },

    // Finish the running job, invoke its callback, and start the next one if
    // any. Returns { start: true, command } when the caller should launch the
    // next process, or { start: false }.
    finishWith: function(result) {
      var callback = current ? current.done : null
      current = null
      handled = true
      if (callback) callback(result)
      if (jobs.length > 0) {
        current = jobs.shift()
        handled = false
        killed = false
        return { start: true, command: current.args }
      }
      return { start: false }
    }
  }
}
