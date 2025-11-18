import mongoose, { Schema } from "mongoose";

const CourseSchema = new Schema(
  {
    courseId: {
      type: String,
      required: true,
      unique: true,
      trim: true,
      lowercase: true,
      index: true,
    },
    name: {
      type: String,
      required: true,
      trim: true,
    },
    qdrantCollection: {
      type: String,
      required: true,
      unique: true,
      trim: true,
      lowercase: true,
      index: true,
    },
    iconUrl: {
      type: String,
      default: null,
    },
    description: {
      type: String,
      default: "",
    },
    isActive: {
      type: Boolean,
      default: true,
      index: true,
    },
    embeddingModel: {
      type: String,
      default: "text-embedding-3-small",
    },
    embeddingDimensions: {
      type: Number,
      default: 1536,
    },
    createdBy: {
      type: Schema.Types.ObjectId,
      ref: "User",
      default: null,
    },
    stats: {
      vectors: { type: Number, default: 0 },
      lastIngestAt: { type: Date, default: null },
    },
  },
  { timestamps: true }
);

export const Course = mongoose.model("Course", CourseSchema);
