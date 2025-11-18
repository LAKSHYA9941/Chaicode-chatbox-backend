import { ask } from "../config/genai.js";
import { Course } from "../models/Course.model.js";
import { Message } from "../models/Message.model.js";

export const askQuestion = async (req, res, next) => {
  try {
    const { query, coursename, courseId } = req.body;
    if (!query) return res.status(400).json({ error: "Missing query" });

    const selectedCourseId = courseId || coursename; // backward compat
    if (!selectedCourseId) {
      return res.status(400).json({ error: "Missing courseId" });
    }

    const course = await Course.findOne({ courseId: selectedCourseId });
    if (!course || !course.isActive) {
      return res.status(404).json({ error: "Course not found or inactive" });
    }

    const started = Date.now();
    let answer;
    try {
      ({ answer } = await ask(query, {
        courseName: course.name,
        collectionName: course.qdrantCollection,
      }));
    } catch (err) {
      if (err?.code === "QDRANT_DIMENSION_MISMATCH") {
        return res.status(503).json({
          error: "VECTOR_DIMENSION_MISMATCH",
          message:
            "Course vector store is outdated. Please re-run ingestion for this course to regenerate embeddings.",
          details: err.details || null,
        });
      }
      throw err;
    }
    const latencyMs = Date.now() - started;

    // fire-and-forget logging
    try {
      await Message.create({
        userId: req.user?._id || null,
        courseId: course.courseId,
        query,
        answer,
        latencyMs,
      });
    } catch (e) {
      console.warn("message log failed", e.message);
    }

    res.json({
      ragAnswer: answer,
      meta: { latencyMs, course: course.courseId },
      quota: req.rateLimit ?? null,
    });
  } catch (err) {
    if (err?.code === "QDRANT_DIMENSION_MISMATCH") {
      return res.status(503).json({
        error: "VECTOR_DIMENSION_MISMATCH",
        message:
          "Course vector store is outdated. Please re-run ingestion for this course to regenerate embeddings.",
        details: err.details || null,
      });
    }
    console.error("Error in askQuestion:", err); // More detailed error logging
    res.status(500).json({
      error: "Error processing your request",
      details: process.env.NODE_ENV === "development" ? err.message : undefined,
    });
  }
};