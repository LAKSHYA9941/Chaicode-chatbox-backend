import mongoose, { Schema } from "mongoose";

const MessageSchema = new Schema(
  {
    userId: { type: Schema.Types.ObjectId, ref: "User", index: true },
    courseId: { type: String, index: true },
    query: { type: String, required: true },
    answer: { type: String, required: true },
    promptTokens: { type: Number, default: 0 },
    completionTokens: { type: Number, default: 0 },
    model: { type: String, default: null },
    latencyMs: { type: Number, default: null },
    error: { type: String, default: null },
  },
  { timestamps: true }
);

export const Message = mongoose.model("Message", MessageSchema);
