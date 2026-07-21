// Express REST /scrape-jobs — cửa 1 (Spec §3.7), contract IC§3.3.
// CHỈ nội bộ compose network; chỉ nhận type "imo_resolve" (Carrier ETA đi cửa MCP riêng).
import express from "express";
import { z } from "zod";

import { scrapeQueue, startWorker, type ScrapeErrorCode } from "./queue.js";
import { startMcpServer } from "./mcp.js";

const SCRAPE_REST_PORT = Number(process.env.SCRAPE_REST_PORT ?? "3000");

const scrapeJobRequest = z.object({
  type: z.literal("imo_resolve"),
  payload: z.object({
    vessel_name: z.string().min(1),
    voyage_no: z.string().nullish(),
    pol: z.string().nullish(),
    pod: z.string().nullish(),
  }),
});

const ERROR_CODES: ScrapeErrorCode[] = [
  "captcha",
  "not_found",
  "ambiguous_name",
  "timeout",
  "login_required",
];

function toErrorCode(failedReason: string | undefined): ScrapeErrorCode {
  const code = ERROR_CODES.find(
    (c) => failedReason === c || failedReason?.startsWith(`${c}`),
  );
  // Lỗi không phân loại được (crash, bug) → timeout: Python fallback §6.7a
  // set manual_required như nhau, không mất thông tin nghiệp vụ.
  return code ?? "timeout";
}

type ScrapeStatus = "queued" | "running" | "succeeded" | "failed";

function toStatus(state: string): ScrapeStatus {
  switch (state) {
    case "completed":
      return "succeeded";
    case "failed":
      return "failed";
    case "active":
      return "running";
    default:
      // waiting / delayed / prioritized / waiting-children
      return "queued";
  }
}

export function createApp(): express.Express {
  const app = express();
  app.use(express.json());

  app.post("/scrape-jobs", async (req, res) => {
    const parsed = scrapeJobRequest.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: "invalid request", details: parsed.error.issues });
      return;
    }
    const job = await scrapeQueue.add(parsed.data.type, parsed.data.payload);
    res.status(202).json({ job_id: String(job.id) });
  });

  app.get("/scrape-jobs/:id", async (req, res) => {
    const job = await scrapeQueue.getJob(req.params.id);
    if (!job) {
      res.status(404).json({ error: "job not found" });
      return;
    }
    const status = toStatus(await job.getState());
    res.status(200).json({
      job_id: String(job.id),
      status,
      result: status === "succeeded" ? job.returnvalue : null,
      error_code: status === "failed" ? toErrorCode(job.failedReason) : null,
    });
  });

  return app;
}

const isMain = process.argv[1]?.endsWith("server.js");
if (isMain) {
  startWorker();
  startMcpServer();
  createApp().listen(SCRAPE_REST_PORT, () => {
    console.log(`[rest] /scrape-jobs listening on :${SCRAPE_REST_PORT}`);
  });
}
