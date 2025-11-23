import "dotenv/config";
import express from "express";
import cors from "cors";
import helmet from "helmet";
import rateLimit from "express-rate-limit";
import fs from "fs";
import askRoutes from "./routes/askRoutes.js";
import authRoutes from "./routes/authRoutes.js";
import oauthRoutes from "./routes/oauthRoutes.js";
import voiceRoutes from "./routes/voiceRoutes.js";
import adminRoutes from "./routes/adminRoutes.js";
import courseRoutes from "./routes/courseRoutes.js";
import healthRoutes from "./routes/healthRoutes.js";
import errorHandler from "./middlewares/errorHandler.js";
import connectDB from "./DB/index.js";
import { Course } from "./models/Course.model.js";

const app = express();
const PORT = process.env.PORT || 5000;

/* ---------- database connection ---------- */
connectDB();

// seed defaults
(async () => {
  try {
    const count = await Course.countDocuments();
    if (count === 0) {
      await Course.create([
        { courseId: "nodejs", name: "Node.js", qdrantCollection: "courses", description: "Server-side JavaScript runtime", isActive: true },
        { courseId: "python", name: "Python", qdrantCollection: "courses", description: "Versatile programming language", isActive: true },
      ]);
      console.log(" Seeded default courses: nodejs, python");
    }
  } catch (e) {
    console.warn("Seed error:", e.message);
  }
})();

/* ---------- middleware ---------- */
// Security
app.use(helmet());
const limiter = rateLimit({
  windowMs: 60 * 1000,
  limit: 120,
});
app.use(limiter);
app.use(
  cors({
    origin: process.env.FRONTEND_URL || "http://localhost:3000",
    credentials: true,
  })
);
app.use(express.json());
// ensure uploads dir exists
try { fs.mkdirSync("uploads", { recursive: true }); } catch { }

/* ---------- routes ---------- */
app.use("/api/ask", askRoutes);
app.use("/api/auth", authRoutes);
app.use("/api/oauth", oauthRoutes);
app.use("/api/voice", voiceRoutes);
app.use("/api/admin", adminRoutes);
app.use("/api/courses", courseRoutes);
app.use("/api/health", healthRoutes);

app.get("/", (req, res) => res.send("Hello World!"));

/* ---------- error handler ---------- */
app.use(errorHandler);

import { client } from "./config/genai.js";

/* ---------- start server ---------- */
app.listen(PORT, async () => {
  console.log(`✅ Backend running at http://localhost:${PORT}`);
  try {
    const collections = await client.getCollections();
    console.log("✅ Connected to Qdrant:", process.env.QDRANT_URL);
    console.log("   Collections:", collections.collections.map(c => c.name).join(", ") || "None");
  } catch (err) {
    console.error("❌ Failed to connect to Qdrant:", err.message);
  }
});