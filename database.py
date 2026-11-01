from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
import os
import re

MONGO_URL = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
db = client.consumer_court_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

# The four court halls. bench_id stays the internal key used by cause lists, users and kiosks;
# hall_no / commission are what the displays show. Names and coram are edited in the Admin Directory.
DEFAULT_HALLS = [
    {"bench_id": "BENCH-1", "hall_no": 1, "commission": "State Commission (Principal Bench)",
     "room_title": "First Floor", "coram": "Hon'ble Justice Sangita Dhingra Sehgal (President) & Ms. Pinki, Member (Judicial)"},
    {"bench_id": "BENCH-2", "hall_no": 2, "commission": "District Commission-I",
     "room_title": "Second Floor", "coram": "Hon'ble Mr. Rajan Sharma"},
    {"bench_id": "BENCH-3", "hall_no": 3, "commission": "District Commission-II",
     "room_title": "Ground Floor", "coram": "Hon'ble President Mr. Justice C.P. Sen"},
    {"bench_id": "BENCH-4", "hall_no": 4, "commission": "State Commission (Additional Bench)",
     "room_title": "", "coram": ""},
]


async def ensure_halls():
    """Create any missing hall and backfill hall_no / commission on halls created before they existed."""
    for hall in DEFAULT_HALLS:
        bench_id = hall["bench_id"]
        await db.benches.update_one(
            {"bench_id": bench_id},
            {"$setOnInsert": {**hall, "state": "In Session", "active_case": None,
                              "ticker_message": f"Hall No. {hall['hall_no']} in session."}},
            upsert=True,
        )
        existing = await db.benches.find_one({"bench_id": bench_id})
        backfill = {k: hall[k] for k in ("hall_no", "commission") if not existing.get(k)}
        # Old titles like "Court Hall No. 1 (First Floor)" become just the location
        old_title = re.match(r"^\s*Court Hall No\.?\s*\d+\s*\((.*)\)\s*$", existing.get("room_title") or "")
        if old_title:
            backfill["room_title"] = old_title.group(1)
        if backfill:
            await db.benches.update_one({"bench_id": bench_id}, {"$set": backfill})

    # "Risen" and "Lunch Recess" states were removed; put any hall still in them back in session
    await db.benches.update_many(
        {"state": {"$regex": "risen|lunch|recess", "$options": "i"}},
        {"$set": {"state": "In Session"}},
    )


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

        await ensure_halls()
        print("✅ Database connected and seeded successfully!")
    except Exception as e:
        print(f"❌ MONGODB CONNECTION FAILED: {e}")