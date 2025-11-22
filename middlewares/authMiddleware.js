import jwt from 'jsonwebtoken';
import NodeCache from 'node-cache';
import { User } from '../models/User.models.js';
import asyncHandler from '../utils/asynchandler.js';

// Cache for 5 minutes (300 seconds)
const userCache = new NodeCache({ stdTTL: 300 });

export const authenticateToken = asyncHandler(async (req, res, next) => {
    const authHeader = req.headers.authorization;
    const token = authHeader && authHeader.split(' ')[1]; // Bearer TOKEN

    if (!token) {
        // console.log("❌ Auth Failed: No token provided in Authorization header");
        return res.status(401).json({ message: "Access token is required" });
    }

    const secret = process.env.ACCESS_TOKEN_SECRET;
    if (!secret) {
        console.error("❌ CRITICAL: ACCESS_TOKEN_SECRET is not defined in environment variables!");
    }

    try {
        const decoded = jwt.verify(token, secret || "your-secret-key");
        const userId = decoded.id || decoded.userId;

        // Check cache first
        let user = userCache.get(userId);

        if (!user) {
            // Not in cache, fetch from DB
            user = await User.findById(userId).select("-password");

            if (!user) {
                console.log(`❌ Auth Failed: User not found in DB. Token ID: ${userId}`);
                return res.status(401).json({ message: "User not found. Please login again." });
            }

            // Store in cache
            userCache.set(userId, user);
        }

        req.user = user;
        next();
    } catch (error) {
        console.log("❌ Auth Failed:", error.message);
        if (error.name === 'TokenExpiredError') {
            return res.status(401).json({ message: "Token has expired. Please login again." });
        }
        return res.status(403).json({ message: "Invalid token. Please login again." });
    }
});

export default authenticateToken;
