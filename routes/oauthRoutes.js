import { Router } from "express";
import { googleAuth } from "../controllers/oauthController.js";

const router = Router();

router.post("/google", googleAuth);

export default router;
