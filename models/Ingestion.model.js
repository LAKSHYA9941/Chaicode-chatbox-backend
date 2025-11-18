import mongoose, { Schema } from "mongoose";

const IngestionSchema = new Schema(
  {
    courseId: { type: String, required: true, index: true },
    status: {
      type: String,
      enum: ["pending", "running", "completed", "failed"],
      default: "pending",
      index: true,
    },
    files: [{ filename: String, size: Number }],
    totalChunks: { type: Number, default: 0 },
    upserted: { type: Number, default: 0 },
    error: { type: String, default: null },
    startedAt: { type: Date, default: null },
    finishedAt: { type: Date, default: null },
    createdBy: { type: Schema.Types.ObjectId, ref: "User", default: null },
    progress: {
      processedFiles: { type: Number, default: 0 },
      totalFiles: { type: Number, default: 0 },
      lastFile: { type: String, default: null },
      lastDocs: { type: Number, default: 0 },
      totalDocs: { type: Number, default: 0 },
      updatedAt: { type: Date, default: null },
    },
  },
  { timestamps: true }
);

export const Ingestion = mongoose.model("Ingestion", IngestionSchema);
