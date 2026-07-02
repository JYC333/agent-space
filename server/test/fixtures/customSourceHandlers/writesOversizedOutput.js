const fs = require("node:fs");
const path = require("node:path");

fs.writeFileSync(path.join(process.cwd(), "output.json"), "x".repeat(5000), "utf8");
