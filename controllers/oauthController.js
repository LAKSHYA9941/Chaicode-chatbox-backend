import { OAuth2Client } from "google-auth-library";
import asyncHandler from "../utils/asynchandler.js";
import { User } from "../models/User.models.js";

const client = new OAuth2Client(process.env.GOOGLE_CLIENT_ID);

export const googleAuth = asyncHandler(async (req, res) => {
  const { idToken, accessToken } = req.body;
  if (!idToken && !accessToken) {
    return res.status(400).json({ message: "Missing Google token" });
  }

  let email, name, picture, sub;

  if (idToken) {
    const ticket = await client.verifyIdToken({
      idToken,
      audience: process.env.GOOGLE_CLIENT_ID,
    });
    const payload = ticket.getPayload();
    if (!payload?.email_verified) {
      return res.status(401).json({ message: "Google email not verified" });
    }
    ({ sub, email, name, picture } = payload);
  } else if (accessToken) {
    const response = await fetch(`https://www.googleapis.com/oauth2/v3/userinfo`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (!response.ok) {
      return res.status(401).json({ message: "Invalid access token" });
    }

    const payload = await response.json();
    if (!payload.email_verified) {
      return res.status(401).json({ message: "Google email not verified" });
    }
    ({ sub, email, name, picture } = payload);
  }

  const { firstName, lastName } = splitName(name);
  const derivedUsername = deriveUsername({ email, name, existingUsername: null });

  let user = await User.findOne({ $or: [{ email }, { googleId: sub }] });
  const now = new Date();

  if (!user) {
    user = new User({
      email,
      name: name || email,
      username: derivedUsername,
      firstname: firstName,
      lastname: lastName,
      avatar: picture || null,
      provider: "google",
      providerId: sub,
      googleId: sub,
      role: "user",
      isSuperuser: false,
      lastLoginAt: now,
      lastSeenAt: now,
    });
  } else {
    user.name = name || user.name;
    user.username = user.username || deriveUsername({ email, name, existingUsername: user.username });
    user.firstname = user.firstname || firstName;
    user.lastname = user.lastname || lastName;
    user.avatar = picture || user.avatar;
    user.provider = user.provider || "google";
    user.providerId = user.providerId || sub;
    user.googleId = user.googleId || sub;
    user.lastLoginAt = now;
    user.lastSeenAt = now;
  }

  // Promote to superuser if matches env
  if (process.env.SUPERUSER_EMAIL && email.toLowerCase() === process.env.SUPERUSER_EMAIL.toLowerCase()) {
    user.role = "superadmin";
    user.isSuperuser = true;
  }

  const refreshToken = user.generateRefreshToken();
  user.refreshToken = refreshToken;
  await user.save();

  const token = user.generateAuthToken();
  const userResponse = {
    _id: user._id,
    email: user.email,
    name: user.name,
    username: user.username,
    firstname: user.firstname,
    lastname: user.lastname,
    avatar: user.avatar,
    role: user.role,
    isSuperuser: user.isSuperuser,
    lastLoginAt: user.lastLoginAt,
    lastSeenAt: user.lastSeenAt,
  };

  return res.status(200).json({ message: "Login successful", token, refreshToken, user: userResponse });
});

export default { googleAuth };

function splitName(fullName) {
  if (!fullName) return { firstName: null, lastName: null };
  const parts = fullName.trim().split(/\s+/);
  if (parts.length === 1) {
    return { firstName: parts[0], lastName: null };
  }
  return { firstName: parts[0], lastName: parts.slice(1).join(" ") };
}

function deriveUsername({ email, name, existingUsername }) {
  if (existingUsername) return existingUsername;
  const base =
    existingUsername ||
    (email ? email.split("@")[0] : null) ||
    (name ? name.replace(/\s+/g, "").toLowerCase() : null);
  if (!base) return `user${Math.floor(Math.random() * 10000)}`;
  return base.toLowerCase().replace(/[^a-z0-9]+/g, "").slice(0, 30) || base;
}
