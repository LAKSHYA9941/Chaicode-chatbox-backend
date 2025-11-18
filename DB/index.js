import mongoose from "mongoose";

const connectDB = async () => {
    console.log('🔄 Attempting to connect to MongoDB...');
    console.log('📍 MongoDB URI:', process.env.MONGODB_URI ? 'URI exists' : 'URI missing');

    try {
        const connectionINST = await mongoose.connect(process.env.MONGODB_URI, {
            dbName: "chatbox"
        });
        console.log(`✅ MongoDB connected to: ${connectionINST.connection.host}/${connectionINST.connection.name}`);
        console.log('📊 Database name:', connectionINST.connection.name);
    } catch (error) {
        console.log(`❌ MongoDB connection error: ${error.message}`);
        console.log(`❌ Full error:`, error);
        process.exit(1);
    }
};

export default connectDB;
