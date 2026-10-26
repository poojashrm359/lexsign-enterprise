from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
import pandas as pd
import io
import os

from database import db, pwd_context, seed_database

app = FastAPI(title="Consumer Court Signage API", version="3.7")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "frontend", "index.html")

@app.get("/")
async def read_index():
    if not os.path.exists(INDEX_PATH):
        return {"error": f"index.html not found at expected path: {INDEX_PATH}"}
    return FileResponse(INDEX_PATH)

@app.on_event("startup")
async def startup_event():
    await seed_database()

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    name: str
    role: str = "READER"
    bench: str = "BENCH-1"

class MatterRequest(BaseModel):
    sr_no: str
    case_no: str
    case_title: str
    complainant_counsel: str
    respondent_counsel: str
    stage: str
    bench_note: str = ""

@app.post("/api/auth/login")
async def login(data: LoginRequest):
    user = await db.users.find_one({"username": data.username})
    if not user or not pwd_context.verify(data.password, user["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    
    return {
        "status": "success",
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
        "bench": user["bench"]
    }

@app.get("/api/admin/users")
async def get_all_users():
    return await db.users.find({}, {"_id": 0, "password": 0}).to_list(100)

@app.post("/api/admin/users")
async def create_or_update_user(data: CreateUserRequest):
    # Enforce strictly 1 Reader per Court Room (Bench)
    if data.bench != "ALL":
        existing_bench_user = await db.users.find_one({"bench": data.bench, "username": {"$ne": data.username}})
        if existing_bench_user:
            # Delete/remove the previous reader assigned to this courtroom
            await db.users.delete_one({"username": existing_bench_user["username"]})

    existing = await db.users.find_one({"username": data.username})
    hashed_pwd = pwd_context.hash(data.password)
    
    if existing:
        await db.users.update_one({"username": data.username}, {"$set": {"name": data.name, "password": hashed_pwd, "role": data.role, "bench": data.bench}})
        return {"status": "success", "message": f"User '{data.name}' updated successfully! (Previous courtroom reader replaced if any)"}
    else:
        await db.users.insert_one({"username": data.username, "password": hashed_pwd, "name": data.name, "role": data.role, "bench": data.bench})
        return {"status": "success", "message": f"New user '{data.name}' created successfully for {data.bench}!"}

@app.delete("/api/admin/users/{username}")
async def delete_user(username: str):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete default admin.")
    await db.users.delete_one({"username": username})
    return {"status": "success", "message": "User deleted."}

@app.get("/api/benches")
async def get_benches():
    return await db.benches.find({}, {"_id": 0}).to_list(100)

@app.post("/api/bench/{bench_id}/state")
async def update_bench_state(bench_id: str, state: str = Form(...)):
    await db.benches.update_one({"bench_id": bench_id}, {"$set": {"state": state}})
    return {"status": "success", "state": state}

@app.post("/api/bench/{bench_id}/ticker")
async def update_ticker(bench_id: str, message: str = Form(...)):
    await db.benches.update_one({"bench_id": bench_id}, {"$set": {"ticker_message": message}})
    return {"status": "success", "message": message}

@app.post("/api/cause-list/upload")
async def upload_cause_list(bench_id: str = Form(...), file: UploadFile = File(...)):
    contents = await file.read()
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
        
        df = df.fillna("")
        records = []
        # Automatically assign clean sequential serial numbers regardless of incoming index formatting
        for idx, row in enumerate(df.iterrows(), start=1):
            row_data = row[1]
            records.append({
                "Sr No.": str(idx),  # Auto-managed serial indexing
                "Case No.": str(row_data.get("Case No.", "")),
                "Case Title & Parties": str(row_data.get("Case Title & Parties", "")),
                "Counsels": str(row_data.get("Counsels", "")),
                "Stage": str(row_data.get("Stage", "")),
                "Status": str(row_data.get("Status", "Scheduled")),
                "Bench Note": str(row_data.get("Bench Note", ""))
            })
        
        await db.cause_lists.update_one(
            {"bench_id": bench_id},
            {"$set": {"matters": records, "updated_at": pd.Timestamp.now().isoformat()}},
            upsert=True
        )
        return {"status": "success", "message": f"Successfully ingested and auto-indexed {len(records)} matters for {bench_id}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")
@app.get("/api/cause-list/{bench_id}")
async def get_cause_list(bench_id: str):
    list_doc = await db.cause_lists.find_one({"bench_id": bench_id}, {"_id": 0})
    if not list_doc:
        return {"bench_id": bench_id, "matters": []}
    
    cleaned_matters = []
    for matter in list_doc.get("matters", []):
        cleaned_matter = {k: ("" if pd.isna(v) else v) for k, v in matter.items()}
        cleaned_matters.append(cleaned_matter)
    list_doc["matters"] = cleaned_matters
    return list_doc

@app.get("/api/consolidated-cause-list")
async def get_consolidated_cause_list():
    benches = await db.benches.find({}, {"_id": 0}).to_list(100)
    all_matters = []
    
    for b in benches:
        bench_id = b["bench_id"]
        list_doc = await db.cause_lists.find_one({"bench_id": bench_id}, {"_id": 0})
        matters = list_doc.get("matters", []) if list_doc else []
        for m in matters:
            cleaned = {k: ("" if pd.isna(v) else v) for k, v in m.items()}
            cleaned["Bench"] = bench_id
            all_matters.append(cleaned)
            
    return {"benches": benches, "matters": all_matters}

@app.post("/api/bench/{bench_id}/action")
async def bench_action(bench_id: str, case_no: str = Form(...), action: str = Form(...)):
    list_doc = await db.cause_lists.find_one({"bench_id": bench_id})
    if list_doc:
        matters = list_doc.get("matters", [])
        for m in matters:
            if m.get("Case No.") == case_no:
                if action == "Call":
                    m["Status"] = "Hearing"
                elif action == "Pass":
                    m["Status"] = "Passed Over"
                elif action == "Adj":
                    m["Status"] = "Adjourned"
                elif action == "Disposed":
                    m["Status"] = "Disposed"
                elif action == "Revert":
                    m["Status"] = "Scheduled"
            elif action == "Call" and m.get("Status") == "Hearing":
                m["Status"] = "Scheduled"
        
        await db.cause_lists.update_one({"bench_id": bench_id}, {"$set": {"matters": matters}})
    
    if action == "Call":
        await db.benches.update_one({"bench_id": bench_id}, {"$set": {"active_case": case_no, "state": "In Session"}})
    elif action in ["Disposed", "Adj"]:
        await db.benches.update_one({"bench_id": bench_id}, {"$set": {"active_case": None}})

    return {"status": "success", "action": action, "case_no": case_no}

@app.delete("/api/cause-list/{bench_id}/clear")
async def clear_cause_list(bench_id: str):
    try:
        # Delete the cause list document for the bench
        result = await db.cause_lists.delete_one({"bench_id": bench_id})
        
        # Reset the bench's active case status
        await db.benches.update_one(
            {"bench_id": bench_id},
            {"$set": {"active_case": None}}
        )
        
        return {
            "status": "success", 
            "message": f"Cause list for {bench_id} cleared successfully!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# GET Atrium Configuration from DB
@app.get("/api/admin/atrium-config")
async def get_atrium_config():
    config = await db.atrium_config.find_one({"_id": "master_atrium"})
    if not config:
        default_config = {
            "_id": "master_atrium",
            "general_announcement": "Welcome to LexSign V3.7 Enterprise Court Complex. Please maintain silence in hallways.",
            "emergency_mode": False
        }
        await db.atrium_config.insert_one(default_config)
        return default_config
    return config

# POST / Update Atrium Configuration in DB
@app.post("/api/admin/atrium-config")
async def update_atrium_config(payload: dict):
    try:
        await db.atrium_config.update_one(
            {"_id": "master_atrium"},
            {"$set": {
                "general_announcement": payload.get("general_announcement"),
                "emergency_mode": payload.get("emergency_mode", False)
            }},
            upsert=True
        )
        return {"status": "success", "message": "Master Atrium configuration updated and saved to DB successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# POST / Update Bench Coram & Room Details
@app.post("/api/admin/bench-config")
async def update_bench_config(payload: dict):
    bench_id = payload.get("bench_id")
    coram = payload.get("coram")
    room_title = payload.get("room_title")

    if not bench_id or not coram:
        raise HTTPException(status_code=400, detail="Bench ID and Coram are required.")

    try:
        update_fields = {"coram": coram}
        if room_title:
            update_fields["room_title"] = room_title

        result = await db.benches.update_one(
            {"bench_id": bench_id},
            {"$set": update_fields}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail=f"Bench {bench_id} not found.")

        return {
            "status": "success", 
            "message": f"Coram for {bench_id} updated successfully to '{coram}'!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cause-list/{bench_id}/add-single")
async def add_single_matter(bench_id: str, data: MatterRequest):
    list_doc = await db.cause_lists.find_one({"bench_id": bench_id})
    matters = list_doc.get("matters", []) if list_doc else []
    
    # Automatically compute the next serial number
    next_sr = str(len(matters) + 1)
    
    new_matter = {
        "Sr No.": next_sr,
        "Case No.": data.case_no,
        "Case Title & Parties": data.case_title,
        "Counsels": f"C: {data.complainant_counsel} | R: {data.respondent_counsel}",
        "Stage": data.stage,
        "Status": "Scheduled",
        "Bench Note": data.bench_note,
        "Bench": bench_id
    }
    matters.append(new_matter)
    
    # Re-index all matters sequentially to ensure no duplicate or broken serial numbers
    for idx, m in enumerate(matters, start=1):
        m["Sr No."] = str(idx)

    await db.cause_lists.update_one({"bench_id": bench_id}, {"$set": {"matters": matters}}, upsert=True)
    return {"status": "success", "message": "Matter added and auto-indexed successfully!"}
    list_doc = await db.cause_lists.find_one({"bench_id": bench_id})
    matters = list_doc.get("matters", []) if list_doc else []
    
    new_matter = {
        "Sr No.": data.sr_no,
        "Case No.": data.case_no,
        "Case Title & Parties": data.case_title,
        "Counsels": f"C: {data.complainant_counsel} | R: {data.respondent_counsel}",
        "Stage": data.stage,
        "Status": "Scheduled",
        "Bench Note": data.bench_note,
        "Bench": bench_id
    }
    matters.append(new_matter)
    await db.cause_lists.update_one({"bench_id": bench_id}, {"$set": {"matters": matters}}, upsert=True)
    return {"status": "success", "message": "Matter added successfully!"}