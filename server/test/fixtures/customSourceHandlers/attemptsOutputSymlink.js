const fs = require("node:fs");
const path = require("node:path");

try {
  fs.symlinkSync(path.join(process.cwd(), "input.json"), path.join(process.cwd(), "output.json"));
  console.log("symlink-succeeded");
} catch (err) {
  console.log(`symlink-blocked:${err.message}`);
}
