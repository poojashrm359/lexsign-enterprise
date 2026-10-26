from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
import os

MONGO_URL = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
db = client.consumer_court_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

async def seed_database():
    try:
        await client.admin.command('ping')
        users_count = await db.users.count_documents({})
        if users_count == 0:
            default_users = [
                {"username": "admin", "password": hash_password("Admin@123"), "role": "ADMIN", "bench": "ALL", "name": "Sh. S.K. Bhattacharya"},
                {"username": "reader1", "password": hash_password("Reader@123"), "role": "READER", "bench": "BENCH-1", "name": "Sh. Amitabh Kant"},
                {"username": "reader2", "password": hash_password("Reader@123"), "role": "READER", "bench": "BENCH-2", "name": "Pooja Sachdeva"},
                {"username": "reader3", "password": hash_password("Reader@123"), "role": "READER", "bench": "BENCH-3", "name": "Vikas Swarup"},
            ]
            await db.users.insert_many(default_users)
            
            benches = [
                {
                    "bench_id": "BENCH-1", 
                    "room_title": "Court Hall No. 1 (First Floor)", 
                    "coram": "Hon'ble Justice Sangita Dhingra Sehgal (President) & Ms. Pinki, Member (Judicial)", 
                    "state": "In Session", 
                    "active_case": "FA/22/2025",
                    "ticker_message": "Court in Session. Matter No. 2 currently being heard."
                },
                {
                    "bench_id": "BENCH-2", 
                    "room_title": "Court Hall No. 2 (Second Floor)", 
                    "coram": "Hon'ble Mr. Rajan Sharma", 
                    "state": "In Session", 
                    "active_case": None,
                    "ticker_message": "Welcome to LexSign Master Atrium Board."
                },
                {
                    "bench_id": "BENCH-3", 
                    "room_title": "Court Hall No. 3 (Ground Floor)", 
                    "coram": "Hon'ble President Mr. Justice C.P. Sen", 
                    "state": "In Session", 
                    "active_case": None,
                    "ticker_message": "Court Hall 3 Proceedings in progress."
                },
            ]
            await db.benches.insert_many(benches)
            print("✅ Database connected and seeded successfully!")
    except Exception as e:
        print(f"❌ MONGODB CONNECTION FAILED: {e}")