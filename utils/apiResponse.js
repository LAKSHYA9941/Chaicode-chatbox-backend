class ApiResponse {
    constructor(data, status, message="Operation successful") {
        this.data = data;
        this.status = status;
        this.message = message;
        this.success = status<400; // Assuming status codes < 400 are successful
        this.errors = null; // No errors by default
        
    }
}
export default ApiResponse;