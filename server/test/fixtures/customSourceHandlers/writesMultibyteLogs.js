// Emits a long run of 3-byte UTF-8 characters so a byte-count truncation
// boundary is very likely to land mid-character somewhere in the stream.
process.stdout.write("中".repeat(2000));
