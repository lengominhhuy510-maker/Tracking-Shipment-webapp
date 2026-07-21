// BullMQ queue + worker cho scrape jobs (IC§3.3). Node KHÔNG chạm Postgres
// (IC§0.1) — kết quả chỉ nằm trong Redis job state, Python poll qua REST.
import { Queue, Worker, type Job } from "bullmq";

import { runImoResolve, type ImoResolvePayload } from "./jobs/imo_resolve.js";

const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379/0";
const SCRAPE_CONCURRENCY = Number(process.env.SCRAPE_CONCURRENCY ?? "2");
const SCRAPE_JOB_TIMEOUT_SECONDS = Number(
  process.env.SCRAPE_JOB_TIMEOUT_SECONDS ?? "90",
);

// error_code khớp enum onboarding_error IC§1.1 (1-1)
export type ScrapeErrorCode =
  | "captcha"
  | "not_found"
  | "ambiguous_name"
  | "timeout"
  | "login_required";

export class ScrapeJobError extends Error {
  constructor(public readonly code: ScrapeErrorCode, message?: string) {
    super(message ?? code);
    this.name = "ScrapeJobError";
  }
}

function redisConnection(url: string) {
  const u = new URL(url);
  return {
    host: u.hostname,
    port: Number(u.port || "6379"),
    db: Number((u.pathname || "/0").slice(1) || "0"),
    password: u.password || undefined,
  };
}

const connection = redisConnection(REDIS_URL);

export const SCRAPE_QUEUE_NAME = "scrape-jobs";

export const scrapeQueue = new Queue(SCRAPE_QUEUE_NAME, {
  connection,
  defaultJobOptions: {
    removeOnComplete: { age: 3600 },
    removeOnFail: { age: 3600 },
    attempts: 1,
  },
});

function withTimeout<T>(promise: Promise<T>, seconds: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new ScrapeJobError("timeout", `job quá ${seconds}s`)),
      seconds * 1000,
    );
    promise.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e);
      },
    );
  });
}

export function startWorker(): Worker {
  const worker = new Worker(
    SCRAPE_QUEUE_NAME,
    async (job: Job) => {
      // Mỗi job 1 browser context riêng — placeholder TASK-10 chưa mở browser;
      // TASK-11 sẽ tạo context trong runImoResolve (1 context/job, đóng trong finally).
      if (job.name !== "imo_resolve") {
        throw new ScrapeJobError("not_found", `unknown job type ${job.name}`);
      }
      return withTimeout(
        runImoResolve(job.data as ImoResolvePayload),
        SCRAPE_JOB_TIMEOUT_SECONDS,
      );
    },
    { connection, concurrency: SCRAPE_CONCURRENCY },
  );
  worker.on("failed", (job, err) => {
    console.error(`[worker] job ${job?.id} failed:`, err.message);
  });
  return worker;
}
