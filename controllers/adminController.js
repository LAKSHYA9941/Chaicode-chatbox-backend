import asyncHandler from "../utils/asynchandler.js";
import { Course } from "../models/Course.model.js";
import { Ingestion } from "../models/Ingestion.model.js";
import { ingestVttFiles } from "../services/ingestionService.js";
import { QdrantClient } from "@qdrant/js-client-rest";

const qdrant = new QdrantClient({ url: process.env.QDRANT_URL || "http://localhost:6333" });

export const createCourse = asyncHandler(async (req, res) => {
  const { courseId, name, iconUrl, description, qdrantCollection } = req.body;
  if (!courseId || !name) {
    return res.status(400).json({ message: "courseId and name are required" });
  }

  const exists = await Course.findOne({ $or: [{ courseId }, { qdrantCollection }] });
  if (exists) {
    return res.status(409).json({ message: "Course with same id or collection exists" });
  }

  const collectionName = (qdrantCollection || `course_${courseId}`).toLowerCase();

  const doc = await Course.create({
    courseId: courseId.toLowerCase(),
    name,
    iconUrl: iconUrl || null,
    description: description || "",
    qdrantCollection: collectionName,
    createdBy: req.user?._id || null,
  });

  res.status(201).json({ course: doc });
});

export const listCourses = asyncHandler(async (_req, res) => {
  const items = await Course.find().sort({ createdAt: -1 });
  res.json({ courses: items });
});

export const updateCourse = asyncHandler(async (req, res) => {
  const { courseId } = req.params;
  const payload = req.body;
  const updated = await Course.findOneAndUpdate({ courseId }, payload, { new: true });
  if (!updated) return res.status(404).json({ message: "Course not found" });
  res.json({ course: updated });
});

export const deleteCourse = asyncHandler(async (req, res) => {
  const { courseId } = req.params;
  const { dropVectors } = req.query;
  const course = await Course.findOne({ courseId });
  if (!course) return res.status(404).json({ message: "Course not found" });

  if (String(dropVectors) === "true") {
    try { await qdrant.deleteCollection(course.qdrantCollection); } catch {}
  }
  await Course.deleteOne({ _id: course._id });
  res.json({ message: "Course deleted" });
});

export const ingestCourse = asyncHandler(async (req, res) => {
  const { courseId } = req.params;
  const forceRecreate = String(req.body?.forceRecreate).toLowerCase() === "true";
  const course = await Course.findOne({ courseId });
  if (!course) return res.status(404).json({ message: "Course not found" });

  if (!req.files || req.files.length === 0) {
    return res.status(400).json({ message: "No files uploaded" });
  }

  const ingestion = await Ingestion.create({
    courseId: course.courseId,
    status: "running",
    files: req.files.map((f) => ({ filename: f.originalname || f.filename, size: f.size })),
    startedAt: new Date(),
    createdBy: req.user?._id || null,
  });

  const progressUpdates = [];

  try {
    const result = await ingestVttFiles({
      course,
      files: req.files,
      forceRecreate,
      onProgress: async (payload) => {
        progressUpdates.push(payload);
        await Ingestion.updateOne({ _id: ingestion._id }, {
          $set: {
            progress: {
              processedFiles: payload.fileIndex ?? 0,
              totalFiles: payload.totalFiles ?? req.files.length,
              lastFile: payload.fileName || null,
              lastDocs: payload.docs ?? 0,
              totalDocs: payload.totalDocs ?? 0,
              updatedAt: payload.timestamp ? new Date(payload.timestamp) : new Date(),
            },
          },
        });
      },
    });
    await Course.updateOne({ _id: course._id }, {
      $set: { "stats.lastIngestAt": new Date() },
      $inc: { "stats.vectors": result.upserted },
    });
    await Ingestion.updateOne({ _id: ingestion._id }, {
      $set: { status: "completed", finishedAt: new Date(), upserted: result.upserted, totalChunks: result.upserted },
    });
    res.json({
      message: "Ingestion completed",
      result,
      forceRecreate,
      progress: progressUpdates,
    });
  } catch (e) {
    await Ingestion.updateOne({ _id: ingestion._id }, {
      $set: { status: "failed", finishedAt: new Date(), error: e.message },
    });
    res.status(500).json({ message: "Ingestion failed", error: e.message });
  }
});

export const getInsights = asyncHandler(async (_req, res) => {
  const { User } = await import("../models/User.models.js");
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const sevenDaysAgo = new Date(now.getTime() - 6 * 24 * 60 * 60 * 1000);
  const startOfWeek = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  const fifteenMinutesAgo = new Date(now.getTime() - 15 * 60 * 1000);

  const totalUsers = await User.countDocuments();
  const totalMessages = await (await import("../models/Message.model.js")).Message.countDocuments();

  const byCourseAgg = await (await import("../models/Message.model.js")).Message.aggregate([
    { $group: { _id: "$courseId", messages: { $sum: 1 } } },
    { $sort: { messages: -1 } },
  ]);

  const ingestions = await Ingestion.find().sort({ createdAt: -1 }).limit(20);
  const courses = await Course.find();

  const [signupsToday, signupsThisWeek, signupsThisMonth, activeWindowCount, redisActiveCount] = await Promise.all([
    User.countDocuments({ createdAt: { $gte: startOfToday } }),
    User.countDocuments({ createdAt: { $gte: startOfWeek } }),
    User.countDocuments({ createdAt: { $gte: startOfMonth } }),
    User.countDocuments({ lastLoginAt: { $gte: fifteenMinutesAgo } }),
    ,
  ]);

  const activeNow = redisActiveCount ?? activeWindowCount;

  const signupTrendRaw = await User.aggregate([
    { $match: { createdAt: { $gte: sevenDaysAgo } } },
    {
      $group: {
        _id: {
          $dateToString: {
            format: "%Y-%m-%d",
            date: "$createdAt",
            timezone: "UTC",
          },
        },
        signups: { $sum: 1 },
      },
    },
    { $sort: { _id: 1 } },
  ]);

  const signupTrendMap = signupTrendRaw.reduce((acc, item) => {
    acc[item._id] = item.signups;
    return acc;
  }, {});

  const signupTrend = Array.from({ length: 7 }).map((_, index) => {
    const date = new Date(now.getTime() - (6 - index) * 24 * 60 * 60 * 1000);
    const key = date.toISOString().slice(0, 10);
    return {
      date: key,
      signups: signupTrendMap[key] ?? 0,
    };
  });

  res.json({
    stats: {
      totalUsers,
      totalMessages,
    },
    userActivity: {
      today: signupsToday,
      week: signupsThisWeek,
      month: signupsThisMonth,
      activeNow,
    },
    signupTrend,
    messagesByCourse: byCourseAgg,
    recentIngestions: ingestions,
    courses,
  });
});
