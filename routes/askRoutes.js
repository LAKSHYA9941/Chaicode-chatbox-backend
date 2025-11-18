import { Router } from "express";
import { askQuestion } from "../controllers/askControllers.js";
import authenticateToken from "../middlewares/authMiddleware.js";
import { dailyQuotaLimiter } from "../middlewares/rateLimiter.js";

const router = Router();

router.post("/", authenticateToken, dailyQuotaLimiter, askQuestion);

export default router;
