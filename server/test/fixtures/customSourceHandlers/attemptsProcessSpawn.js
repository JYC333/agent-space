try {
  require("node:child_process").spawn("echo", ["hi"]);
  console.log("spawn-call-succeeded");
} catch (err) {
  console.log(`spawn-blocked:${err.message}`);
}
try {
  new (require("node:worker_threads").Worker)("console.log(1)", { eval: true });
  console.log("worker-call-succeeded");
} catch (err) {
  console.log(`worker-blocked:${err.message}`);
}
