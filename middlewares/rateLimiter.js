import { RateLimit } from "../models/RateLimit.model.js";

export async function dailyQuotaLimiter(req, res, next) {
  try {
    const user = req.user;
    if (!user?._id) {
      return res.status(401).json({ message: "Please log in to continue." });
    }

    const now = new Date();
    const dateKey = now.toISOString().split("T")[0];
    const result = await RateLimit.findOneAndUpdate(
      { userId: user._id, dateKey },
      { $inc: { count: 1 } },
      {
        new: true,
        upsert: true,
      }
    );

    const quota = {
      limit: 10,
      remaining: Math.max(0, 10 - (result?.count ?? 0)),
    };

    if ((result?.count ?? 0) > 10) {
      const resetAt = new Date(now);
      resetAt.setUTCHours(23, 59, 59, 999);
      return res.status(429).json({
        message: "You've reached today's question limit. Let's pick this up tomorrow!",
        resetAt: resetAt.toISOString(),
        quota,
      });
    }

    req.rateLimit = quota;

    next();
  } catch (error) {
    console.error("dailyQuotaLimiter error", error);
    return res.status(500).json({
      message: "We're having trouble tracking daily usage right now. Please try again shortly.",
    });
  }
}
