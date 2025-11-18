import { Router } from "express";
import multer from "multer";
import path from "path";
import fs from "fs";
import authenticateToken from "../middlewares/authMiddleware.js";
import { dailyQuotaLimiter } from "../middlewares/rateLimiter.js";
import { voiceChat } from "../controllers/voiceController.js";

const router = Router();

// Ensure uploads directory
try { fs.mkdirSync("uploads", { recursive: true }); } catch {}

const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, path.join(process.cwd(), "uploads")),
    filename: (_req, file, cb) => cb(null, `${Date.now()}-${file.originalname}`),
  }),
  limits: {
    fileSize: 15 * 1024 * 1024, // 15 MB
  },
});

// POST /api/voice/turn - field name: audio (binary)
router.post("/turn", authenticateToken, dailyQuotaLimiter, upload.single("audio"), voiceChat);

export default router;
