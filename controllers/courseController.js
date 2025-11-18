import asyncHandler from "../utils/asynchandler.js";
import { Course } from "../models/Course.model.js";

export const listActiveCourses = asyncHandler(async (_req, res) => {
  const items = await Course.find({ isActive: true }).select("courseId name iconUrl description").sort({ name: 1 });
  res.json({ courses: items });
});
