import mongoose, { Schema } from "mongoose";
import jwt from "jsonwebtoken";
import bcrypt from "bcrypt";
// import { use } from "bcrypt/promises";

const UserSchema = new Schema({
    username: {
        type: String,
        required: false,
        unique: false,
        lowercase: true,
        trim: true,
        index: true,
    },
    email: {
        type: String,
        required: true,
        unique: true,
        lowercase: true,
        trim: true,
        index: true,
    },
    name: {
        type: String,
        trim: true,
        default: null,
    },
    firstname: {
        type: String,
        required: false,
        trim: true,
        index: true
    },
    lastname: {
        type: String,
        required: false,
        trim: true,
        index: true
    },
    avatar: {
        type: String, // cloudinary or google avatar url
        required: false,
        default: null
    },
    provider: {
        type: String, // 'credentials' | 'google'
        default: 'credentials',
        index: true
    },
    providerId: {
        type: String, // oauth provider user id
        default: null,
        index: true
    },
    googleId: {
        type: String,
        default: null,
        index: true
    },
    role: {
        type: String,
        enum: ['user', 'admin', 'superadmin'],
        default: 'user',
        index: true
    },
    isSuperuser: {
        type: Boolean,
        default: false,
        index: true
    },
    lastLoginAt: {
        type: Date,
        default: null
    },
    lastSeenAt: {
        type: Date,
        default: null
    },
    coverimage: {
        type: String, //cloudinary url
    },
    watchHistory: {
        type: [{ type: Schema.Types.ObjectId, ref: "Video" }],
        default: []
    },
    password: {
        type: String,
        required: function() { return !this.provider || this.provider === 'credentials'; }
    },
    refreshToken: {
        type: String
    },

}, {
    timestamps: true
})

UserSchema.pre("save", async function (next) {
    if (!this.isModified("password") || !this.password) return next();
    this.password = await bcrypt.hash(this.password, 10);
    next();
});

UserSchema.methods.isCorrectPassword = async function (password) {
    return await bcrypt.compare(password, this.password);
}

UserSchema.methods.generateAuthToken = function () {
    const payload = {
        id: this._id,
        username: this.username,
        email: this.email,
        firstname: this.firstname,
        lastname: this.lastname,
        name: this.name,
        avatar: this.avatar,
        role: this.role,
        isSuperuser: this.isSuperuser
    };
    return jwt.sign(payload, process.env.ACCESS_TOKEN_SECRET, { expiresIn: process.env.ACCESS_TOKEN_EXPIRES_IN });
}

UserSchema.methods.generateRefreshToken = function () {
    return jwt.sign({ id: this._id }, process.env.REFRESH_TOKEN_SECRET, { expiresIn: process.env.REFRESH_TOKEN_EXPIRES_IN });
}

export const User = mongoose.model("User", UserSchema);