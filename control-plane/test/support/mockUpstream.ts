import http from "node:http";
import type { AddressInfo } from "node:net";

export interface CapturedRequest {
  method: string;
  url: string;
  headers: http.IncomingHttpHeaders;
  body: string;
  rawBody: Buffer;
}

export interface MockUpstream {
  baseUrl: string;
  requests: CapturedRequest[];
  close: () => Promise<void>;
}

export async function startMockUpstream(
  handler?: (req: CapturedRequest, res: http.ServerResponse) => void,
): Promise<MockUpstream> {
  const requests: CapturedRequest[] = [];
  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c as Buffer));
    req.on("end", () => {
      const rawBody = Buffer.concat(chunks);
      const captured: CapturedRequest = {
        method: req.method ?? "",
        url: req.url ?? "",
        headers: req.headers,
        body: rawBody.toString("utf8"),
        rawBody,
      };
      requests.push(captured);
      if (handler) {
        handler(captured, res);
        return;
      }
      res.writeHead(200, { "content-type": "application/json", "x-upstream": "python" });
      res.end(JSON.stringify({ ok: true, seen_path: captured.url }));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  return {
    baseUrl: `http://127.0.0.1:${port}`,
    requests,
    close: () =>
      new Promise<void>((resolve, reject) =>
        server.close((err) => (err ? reject(err) : resolve())),
      ),
  };
}
