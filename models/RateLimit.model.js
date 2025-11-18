import mongoose, { Schema } from "mongoose";

const RateLimitSchema = new Schema(
  {
    userId: {
      type: Schema.Types.ObjectId,
      ref: "User",
      required: true,
      index: true,
    },
    dateKey: {
      type: String,
      required: true,
      index: true,
    },
    count: {
      type: Number,
      default: 0,
    },
    metadata: {
      type: Schema.Types.Mixed,
      default: {},
    },
  },
  { timestamps: true }
);

RateLimitSchema.index({ userId: 1, dateKey: 1 }, { unique: true });

export const RateLimit = mongoose.model("RateLimit", RateLimitSchema);
