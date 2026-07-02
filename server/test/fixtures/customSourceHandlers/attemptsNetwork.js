try {
  require("node:http").get("http://example.com/", () => {});
  console.log("http-call-succeeded");
} catch (err) {
  console.log(`http-blocked:${err.message}`);
}
try {
  fetch("https://example.com/");
  console.log("fetch-call-succeeded");
} catch (err) {
  console.log(`fetch-blocked:${err.message}`);
}
