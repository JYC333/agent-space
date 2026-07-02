const fs = require("node:fs");
const path = require("node:path");

const input = JSON.parse(fs.readFileSync(path.join(process.cwd(), "input.json"), "utf8"));
console.log(`handler saw connection ${input.source.name}`);
fs.writeFileSync(
  path.join(process.cwd(), "output.json"),
  JSON.stringify({
    contract_version: "custom_source.handler_output.v1",
    items: [],
    diagnostics: { warnings: [] },
  }),
  "utf8",
);
