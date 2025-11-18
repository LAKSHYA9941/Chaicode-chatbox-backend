import { Router } from "express";
import { listActiveCourses } from "../controllers/courseController.js";

const router = Router();

router.get("/", listActiveCourses);

export default router;
