import { Router } from "express";
import multer from "multer";
import path from "path";
import authenticateToken from "../middlewares/authMiddleware.js";
import requireSuperuser from "../middlewares/roleMiddleware.js";
import {
  createCourse,
  listCourses,
  updateCourse,
  deleteCourse,
  ingestCourse,
  getInsights,
} from "../controllers/adminController.js";

const router = Router();
const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, path.join(process.cwd(), "uploads")),
    filename: (_req, file, cb) => cb(null, `${Date.now()}-${file.originalname}`),
  }),
  fileFilter: (_req, file, cb) => {
    if (file.originalname.toLowerCase().endsWith(".vtt")) cb(null, true);
    else cb(new Error("Only .vtt files are allowed"));
  },
});

router.use(authenticateToken, requireSuperuser);

router.post("/courses", createCourse);
router.get("/courses", listCourses);
router.put("/courses/:courseId", updateCourse);
router.delete("/courses/:courseId", deleteCourse);

router.post("/ingest/:courseId", upload.array("files", 500), ingestCourse);

router.get("/insights", getInsights);

export default router;
