from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
import pandas as pd
import io
import os
import re

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

KIOSK_SCREENS = {"court-1", "court-2", "court-3", "court-4", "master-1", "master-2", "master-3", "master-4"}


def serve_index():
    if not os.path.exists(INDEX_PATH):
        return {"error": f"index.html not found at expected path: {INDEX_PATH}"}
    return FileResponse(INDEX_PATH)


@app.get("/")
async def read_index():
    return serve_index()


@app.get("/display/{screen_id}")
async def kiosk_display(screen_id: str):
    """Dedicated kiosk URLs for the registered hallway/court and master screens."""
    if screen_id.lower() not in KIOSK_SCREENS:
        raise HTTPException(status_code=404, detail="Unknown display screen")
    return serve_index()

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
    sr_no: str = ""  # ignored: serial numbers are assigned automatically
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

async def hall_label(bench_id: str) -> str:
    """Human-readable hall name for a bench id, e.g. 'BENCH-1' -> 'Hall No. 1'."""
    if bench_id == "ALL":
        return "Admin (All Halls)"
    bench_doc = await db.benches.find_one({"bench_id": bench_id})
    hall_no = bench_doc.get("hall_no") if bench_doc else None
    return f"Hall No. {hall_no}" if hall_no else bench_id

@app.post("/api/admin/users")
async def create_or_update_user(data: CreateUserRequest):
    # A username belongs to exactly one hall; never silently move it to another hall
    existing = await db.users.find_one({"username": data.username})
    if existing and existing.get("bench") != data.bench:
        assigned_to = await hall_label(existing.get("bench"))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{data.username}' is already assigned to {assigned_to} ({existing.get('name')}). Please choose a different username."
        )

    # Enforce strictly 1 Reader per Court Room (Bench)
    if data.bench != "ALL":
        existing_bench_user = await db.users.find_one({"bench": data.bench, "username": {"$ne": data.username}})
        if existing_bench_user:
            # Delete/remove the previous reader assigned to this courtroom
            await db.users.delete_one({"username": existing_bench_user["username"]})

    hashed_pwd = pwd_context.hash(data.password)
    hall = await hall_label(data.bench)

    if existing:
        await db.users.update_one({"username": data.username}, {"$set": {"name": data.name, "password": hashed_pwd, "role": data.role, "bench": data.bench}})
        return {"status": "success", "message": f"User '{data.name}' updated successfully for {hall}!"}
    else:
        await db.users.insert_one({"username": data.username, "password": hashed_pwd, "name": data.name, "role": data.role, "bench": data.bench})
        return {"status": "success", "message": f"New user '{data.name}' created successfully for {hall}!"}

@app.delete("/api/admin/users/{username}")
async def delete_user(username: str):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete default admin.")
    await db.users.delete_one({"username": username})
    return {"status": "success", "message": "User deleted."}

@app.get("/api/benches")
async def get_benches():
    return await db.benches.find({}, {"_id": 0}).sort([("hall_no", 1), ("bench_id", 1)]).to_list(100)

@app.post("/api/bench/{bench_id}/state")
async def update_bench_state(bench_id: str, state: str = Form(...)):
    await db.benches.update_one({"bench_id": bench_id}, {"$set": {"state": state}})
    return {"status": "success", "state": state}

@app.post("/api/bench/{bench_id}/ticker")
async def update_ticker(bench_id: str, message: str = Form(...)):
    await db.benches.update_one({"bench_id": bench_id}, {"$set": {"ticker_message": message}})
    return {"status": "success", "message": message}

def _norm_header(h) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(h).lower()).split())


def _classify_header(h: str):
    """Map a free-form Excel header to one of our matter fields (None = ignore)."""
    n = _norm_header(h)
    if not n or n.startswith("unnamed"):
        return None
    words = set(n.split())
    if n in ("sr", "sr no", "s no", "sno", "sl", "sl no", "serial", "serial no", "item no", "no", "item") or words & {"sr", "sno", "serial"}:
        return "Sr No."
    if words & {"counsel", "counsels", "advocate", "advocates", "lawyer", "lawyers"}:
        return "Counsels"
    if "status" in words:
        return "Status"
    if words & {"stage", "purpose"}:
        return "Stage"
    if words & {"note", "notes", "remark", "remarks"}:
        return "Bench Note"
    if ("case" in words or words & {"complaint", "appeal", "petition", "file", "diary", "fa", "cc", "rp"}) and words & {"no", "number", "num", "id"}:
        return "Case No."
    if words & {"title", "party", "parties", "vs", "versus", "v", "complainant", "complainants", "opposite",
                "respondent", "respondents", "appellant", "appellants", "petitioner", "petitioners", "name", "names"}:
        return "Case Title & Parties"
    if "case" in words:
        return "Case No."
    return None


# Used when no recognisable header row exists: Case No., Parties, Counsels, Stage in column order
POSITIONAL_FIELDS = ["Case No.", "Case Title & Parties", "Counsels", "Stage"]


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def parse_cause_list(raw: pd.DataFrame) -> list:
    """Turn a headerless sheet into matter records, regardless of the exact header wording."""
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if raw.empty:
        return []

    # Pick the header row (within the first 15 rows) that maps the most columns
    best_row, best_map = None, {}
    for r in range(min(15, len(raw))):
        mapping = {c: f for c, v in raw.iloc[r].items() if (f := _classify_header(_cell(v)))}
        if len(set(mapping.values())) > len(set(best_map.values())):
            best_row, best_map = r, mapping

    if best_row is not None and len(set(best_map.values()) - {"Sr No."}) >= 2:
        data = raw.iloc[best_row + 1:]
        col_map = best_map
    else:
        data = raw
        cols = list(raw.columns)
        # Skip a leading serial-number column
        first = [_cell(v) for v in raw[cols[0]]]
        if first and all(x.replace(".", "").isdigit() for x in first if x):
            cols = cols[1:]
        col_map = dict(zip(cols, POSITIONAL_FIELDS))

    records = []
    for _, row in data.iterrows():
        rec = {}
        for col, field in col_map.items():
            if field == "Sr No.":
                continue
            val = _cell(row[col])
            if not val:
                continue
            # Several columns can map to one field (e.g. Complainant + Opposite Party)
            sep = " vs " if field == "Case Title & Parties" else " | "
            rec[field] = f"{rec[field]}{sep}{val}" if field in rec else val
        if not any(rec.get(f) for f in ("Case No.", "Case Title & Parties", "Counsels")):
            continue
        status, next_date = rec.get("Status") or "Scheduled", ""
        # A re-uploaded export carries "Next Hearing: DD/MM/YYYY"; store it as a normal adjournment
        next_hearing = re.match(r"^\s*next\s+hearing\s*:?\s*(.+)$", status, re.IGNORECASE)
        if next_hearing:
            status, next_date = "Adjourned", next_hearing.group(1).strip()
        records.append({
            "Sr No.": str(len(records) + 1),  # Auto-managed serial indexing
            "Case No.": rec.get("Case No.", ""),
            "Case Title & Parties": rec.get("Case Title & Parties", ""),
            "Counsels": rec.get("Counsels", ""),
            "Stage": rec.get("Stage", ""),
            "Status": status,
            "Next Date": next_date,
            "Bench Note": rec.get("Bench Note", ""),
        })
    return records


@app.post("/api/cause-list/upload")
async def upload_cause_list(bench_id: str = Form(...), file: UploadFile = File(...)):
    contents = await file.read()
    try:
        if file.filename.lower().endswith('.csv'):
            raw = pd.read_csv(io.BytesIO(contents), header=None, dtype=str)
        else:
            raw = pd.read_excel(io.BytesIO(contents), header=None, dtype=str)

        records = parse_cause_list(raw)
        
        await db.cause_lists.update_one(
            {"bench_id": bench_id},
            {"$set": {"matters": records, "updated_at": pd.Timestamp.now().isoformat()}},
            upsert=True
        )
        return {"status": "success", "message": f"Successfully ingested and auto-indexed {len(records)} matters for {await hall_label(bench_id)}"}
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
    benches = await get_benches()
    all_matters = []
    
    for b in benches:
        bench_id = b["bench_id"]
        list_doc = await db.cause_lists.find_one({"bench_id": bench_id}, {"_id": 0})
        matters = list_doc.get("matters", []) if list_doc else []
        for m in matters:
            cleaned = {k: ("" if pd.isna(v) else v) for k, v in m.items()}
            cleaned["Bench"] = bench_id
            cleaned["Hall"] = f"Hall No. {b['hall_no']}" if b.get("hall_no") else bench_id
            all_matters.append(cleaned)
            
    return {"benches": benches, "matters": all_matters}

@app.post("/api/bench/{bench_id}/action")
async def bench_action(bench_id: str, case_no: str = Form(...), action: str = Form(...), next_date: str = Form(None)):
    list_doc = await db.cause_lists.find_one({"bench_id": bench_id})
    if list_doc:
        matters = list_doc.get("matters", [])
        for m in matters:
            if m.get("Case No.") == case_no:
                if action == "Call":
                    m["Status"] = "Hearing"
                    m["Next Date"] = ""
                elif action == "Pass":
                    m["Status"] = "Passed Over"
                elif action == "Adj":
                    m["Status"] = "Adjourned"
                    m["Next Date"] = next_date or ""
                elif action == "Closed":
                    m["Status"] = "Closed"
                    m["Next Date"] = ""
                elif action == "Disposed":
                    m["Status"] = "Disposed"
                elif action == "Revert":
                    m["Status"] = "Scheduled"
                    m["Next Date"] = ""
            elif action == "Call" and m.get("Status") == "Hearing":
                m["Status"] = "Scheduled"
        
        await db.cause_lists.update_one({"bench_id": bench_id}, {"$set": {"matters": matters}})
    
    if action == "Call":
        await db.benches.update_one({"bench_id": bench_id}, {"$set": {"active_case": case_no, "state": "In Session"}})
    elif action in ["Disposed", "Adj", "Closed"]:
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
    commission = payload.get("commission")

    if not bench_id or not coram:
        raise HTTPException(status_code=400, detail="Hall and Coram are required.")

    try:
        update_fields = {"coram": coram}
        if room_title is not None:
            update_fields["room_title"] = room_title
        if commission:
            update_fields["commission"] = commission

        result = await db.benches.update_one(
            {"bench_id": bench_id},
            {"$set": update_fields}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail=f"Bench {bench_id} not found.")

        return {
            "status": "success", 
            "message": "Hall details updated successfully!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def _load_matters_or_404(bench_id: str, index: int) -> list:
    list_doc = await db.cause_lists.find_one({"bench_id": bench_id})
    matters = list_doc.get("matters", []) if list_doc else []
    if not 0 <= index < len(matters):
        raise HTTPException(status_code=404, detail="Matter not found")
    return matters


@app.put("/api/cause-list/{bench_id}/matter/{index}")
async def edit_matter(bench_id: str, index: int, data: MatterRequest):
    matters = await _load_matters_or_404(bench_id, index)
    m = matters[index]
    old_case_no = m.get("Case No.")
    m.update({
        "Case No.": data.case_no,
        "Case Title & Parties": data.case_title,
        "Counsels": f"C: {data.complainant_counsel} | R: {data.respondent_counsel}",
        "Stage": data.stage,
        "Bench Note": data.bench_note,
    })
    await db.cause_lists.update_one({"bench_id": bench_id}, {"$set": {"matters": matters}})
    # Keep the live display pointing at the renamed case
    if old_case_no != data.case_no:
        await db.benches.update_one({"bench_id": bench_id, "active_case": old_case_no}, {"$set": {"active_case": data.case_no}})
    return {"status": "success", "message": "Matter updated successfully!"}


@app.delete("/api/cause-list/{bench_id}/matter/{index}")
async def delete_matter(bench_id: str, index: int):
    matters = await _load_matters_or_404(bench_id, index)
    removed = matters.pop(index)
    for idx, m in enumerate(matters, start=1):
        m["Sr No."] = str(idx)
    await db.cause_lists.update_one({"bench_id": bench_id}, {"$set": {"matters": matters}})
    await db.benches.update_one({"bench_id": bench_id, "active_case": removed.get("Case No.")}, {"$set": {"active_case": None}})
    return {"status": "success", "message": "Matter deleted successfully!"}


EXPORT_COLUMNS = ["Sr No.", "Case No.", "Case Title & Parties", "Counsels", "Stage", "Status", "Bench Note"]


def _export_status(m: dict) -> str:
    """Status as shown in the Reader Console: an adjourned matter shows its next hearing date."""
    status = _cell(m.get("Status")) or "Scheduled"
    next_date = _cell(m.get("Next Date"))
    if status.lower() == "adjourned" and next_date:
        return f"Next Hearing: {next_date}"
    return status


@app.get("/api/cause-list/{bench_id}/export")
async def export_cause_list(bench_id: str):
    list_doc = await db.cause_lists.find_one({"bench_id": bench_id})
    matters = list_doc.get("matters", []) if list_doc else []
    rows = [{**{c: _cell(m.get(c, "")) for c in EXPORT_COLUMNS}, "Status": _export_status(m)} for m in matters]
    df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Cause List")
        ws = writer.sheets["Cause List"]
        for col_cells in ws.columns:
            width = max(len(str(c.value or "")) for c in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max(width + 2, 10), 60)
    buf.seek(0)

    filename = f"{bench_id}_cause_list_{pd.Timestamp.now():%Y-%m-%d}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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