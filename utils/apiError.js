class ApiError extends Error {
    constructor(
        message = "Something went wrong",
        statusCode,
        stack = "",
        errors = []
    ) {
        super(message);
        this.statusCode = statusCode || 500;
        this.errors = errors;
        this.data = null;

        if (stack) {
            this.stack = stack;
        } else {
            Error.captureStackTrace(this, this.constructor);
        }
    }
}

export default ApiError;
