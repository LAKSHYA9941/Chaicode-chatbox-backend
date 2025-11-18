import express from 'express';
import {
    registerUser,
    loginUser,
    logoutUser,
    refreshToken
} from '../controllers/authControllers.js';
import authenticateToken from '../middlewares/authMiddleware.js';

const router = express.Router();

// Public routes
router.post('/register', registerUser);
router.post('/login', loginUser);
router.post('/refresh-token', refreshToken);

// Protected routes (require authentication)
router.post('/logout', authenticateToken, logoutUser);

export default router;