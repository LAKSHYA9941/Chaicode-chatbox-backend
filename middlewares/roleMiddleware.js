import asyncHandler from "../utils/asynchandler.js";

export const requireSuperuser = asyncHandler(async (req, _res, next) => {
  if (!req.user || (!req.user.isSuperuser && req.user.role !== "superadmin")) {
    const err = new Error("Forbidden: Superuser access required");
    err.status = 403;
    throw err;
  }
  next();
});

export default requireSuperuser;
