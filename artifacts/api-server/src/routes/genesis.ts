/**
 * Genesis Engine proxy routes
 * Forwards /api/genesis/* requests to the Python genesis-engine service.
 */

import express from "express";
import { logger } from "../lib/logger.js";

const router = express.Router();

const GENESIS_ENGINE_URL =
  process.env.GENESIS_ENGINE_URL ?? "http://localhost:8000";

async function proxyToEngine(
  path: string,
  req: express.Request,
  res: express.Response,
): Promise<void> {
  const url = `${GENESIS_ENGINE_URL}${path}`;
  try {
    const hasBody =
      ["POST", "PUT", "PATCH"].includes(req.method) &&
      req.body !== undefined &&
      Object.keys(req.body).length > 0;

    const upstream = await fetch(url, {
      method: req.method,
      headers: { "Content-Type": "application/json" },
      body: hasBody ? JSON.stringify(req.body) : undefined,
    });

    const data = await upstream.json();
    res.status(upstream.status).json(data);
  } catch (err) {
    logger.warn({ err, url }, "Genesis engine unreachable");
    res
      .status(502)
      .json({ error: "Genesis engine unavailable — is the Python service running?" });
  }
}

// Health / status
router.get("/status", (req, res) => proxyToEngine("/status", req, res));

// Lifecycle controls
router.post("/start", (req, res) => proxyToEngine("/start", req, res));
router.post("/stop", (req, res) => proxyToEngine("/stop", req, res));
router.post("/reset", (req, res) => proxyToEngine("/reset", req, res));

// Data reads
router.get("/history", (req, res) => proxyToEngine("/history", req, res));
router.get("/hall-of-fame", (req, res) =>
  proxyToEngine("/hall-of-fame", req, res),
);
router.get("/audit", (req, res) => proxyToEngine("/audit", req, res));

// Writes
router.post("/settings", (req, res) => proxyToEngine("/settings", req, res));
router.post("/hall-of-fame", (req, res) =>
  proxyToEngine("/hall-of-fame", req, res),
);

export default router;
