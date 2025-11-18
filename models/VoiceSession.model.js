import mongoose, { Schema } from "mongoose";

const VoiceSessionSchema = new Schema(
  {
    userId: {
      type: Schema.Types.ObjectId,
      ref: "User",
      required: true,
    },
    courseId: {
      type: String,
      required: true,
      index: true,
    },
    transcript: {
      type: String,
      default: "",
    },
    answer: {
      type: String,
      default: "",
    },
    responseType: {
      type: String,
      enum: ["audio", "text"],
      default: "audio",
    },
    audioDurationMs: {
      type: Number,
      default: 0,
    },
    meta: {
      type: Schema.Types.Mixed,
      default: {},
    },
  },
  { timestamps: true }
);

export const VoiceSession = mongoose.model("VoiceSession", VoiceSessionSchema);
