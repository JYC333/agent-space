const fs = require("node:fs");
const path = require("node:path");

const input = JSON.parse(fs.readFileSync(path.join(process.cwd(), "input.json"), "utf8"));
console.log(`input-read:${input.source.name}`);

try {
  fs.readFileSync(path.resolve(process.cwd(), "..", "outside.txt"), "utf8");
  console.log("outside-read-succeeded");
} catch (err) {
  console.log(`outside-read-blocked:${err.message}`);
}

try {
  fs.writeFileSync(path.resolve(process.cwd(), "..", "outside.txt"), "nope", "utf8");
  console.log("outside-write-succeeded");
} catch (err) {
  console.log(`outside-write-blocked:${err.message}`);
}

fs.writeFileSync(path.join(process.cwd(), "files", "allowed.txt"), "ok", "utf8");
fs.writeFileSync(
  path.join(process.cwd(), "output.json"),
  JSON.stringify({
    contract_version: "custom_source.handler_output.v1",
    items: [],
    diagnostics: { warnings: [] },
  }),
  "utf8",
);
