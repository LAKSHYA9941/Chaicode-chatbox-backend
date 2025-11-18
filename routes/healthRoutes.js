import { Router } from "express";

const router = Router();

router.get("/health", (req, res) => res.status(200).json({message: "health is OK "}));

export default router;