import express from "express";
import bcrypt from "bcrypt";
import jwt from "jsonwebtoken";
import { User } from "../models/User.models.js";
import asyncHandler from "../utils/asynchandler.js";

const registerUser = asyncHandler(async (req, res) => {
  const { username, email, password, firstname, lastname } = req.body;
  console.log('Registration attempt:', { username, email, firstname, lastname });

  if (!username || !email || !password || !firstname || !lastname) {
    console.log('Missing required fields');
    return res.status(400).json({ message: "All fields are required" });
  }

  const existing = await User.findOne({ email });
  console.log('Existing user check:', existing ? 'User exists' : 'User does not exist');

  if (existing) {
    console.log('User already exists with email:', email);
    return res.status(400).json({ message: "User already exists" });
  }

  const user = new User({
    username,
    email,
    password,
    firstname,
    lastname
  });

  await user.save();
  console.log('User created successfully');
  res.status(201).json({ message: "User registered successfully" });
});

const loginUser = asyncHandler(async (req, res) => {
  const { email, password } = req.body;
  console.log('Login attempt for email:', email);

  const user = await User.findOne({ email });
  if (!user) {
    console.log('Login failed: User not found');
    return res.status(400).json({ message: "Invalid credentials" });
  }

  const isMatch = await bcrypt.compare(password, user.password);
  if (!isMatch) {
    console.log('Login failed: Invalid password');
    return res.status(400).json({ message: "Invalid credentials" });
  }

  // Update last login time
  user.lastLoginAt = new Date();
  user.lastSeenAt = new Date();
  const refreshToken = user.generateRefreshToken();
  user.refreshToken = refreshToken;
  await user.save();

  // Generate JWT token
  const token = user.generateAuthToken();

  // Build user response without sensitive data
  const userResponse = buildUserResponse(user);

  console.log('Login successful for user:', user._id);
  res.status(200).json({
    message: "Login successful",
    token,
    refreshToken,
    user: userResponse
  });
});

const refreshToken = asyncHandler(async (req, res) => {
  const { refreshToken } = req.body;
  if (!refreshToken) {
    return res.status(401).json({ message: "Refresh token is required" });
  }

  const user = await User.findOne({ refreshToken });
  if (!user) {
    return res.status(403).json({ message: "Invalid refresh token" });
  }

  try {
    // Generate new tokens
    const newToken = user.generateAuthToken();
    const newRefreshToken = user.generateRefreshToken();

    // Update refresh token in database
    user.refreshToken = newRefreshToken;
    await user.save();

    res.status(200).json({
      token: newToken,
      refreshToken: newRefreshToken
    });
  } catch (error) {
    console.error('Refresh token error:', error);
    res.status(500).json({ message: "Error refreshing token" });
  }
});

const logoutUser = asyncHandler(async (req, res) => {
  const { userId } = req.user;

  // Clear refresh token
  await User.findByIdAndUpdate(userId, {
    refreshToken: null,
    lastSeenAt: new Date()
  });

  console.log('User logged out:', userId);
  res.status(200).json({ message: "Logged out successfully" });
});

// Helper function to build user response
function buildUserResponse(user) {
  const userObj = user.toObject();
  delete userObj.password;
  delete userObj.refreshToken;
  return userObj;
}

export {
  registerUser,
  loginUser,
  logoutUser,
  refreshToken
};