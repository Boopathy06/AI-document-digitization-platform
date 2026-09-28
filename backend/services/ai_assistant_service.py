"""AI Government Record Assistant & Natural Language Search service for Module 9.

Translates plain English queries into safe, parameterized SQLite queries,
executes them with read-only guarantees, and generates conversational answers
with structured record cards and suggestions.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


TAMIL_NADU_DISTRICTS = [
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore",
    "Dharmapuri", "Dindigul", "Erode", "Kallakurichi", "Kanchipuram",
    "Kanyakumari", "Karur", "Krishnagiri", "Madurai", "Mayiladuthurai",
    "Nagapattinam", "Namakkal", "Nilgiris", "Perambalur", "Pudukkottai",
    "Ramanathapuram", "Ranipet", "Salem", "Sivagangai", "Tenkasi",
    "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli", "Trichy",
    "Tirunelveli", "Tirupathur", "Tiruppur", "Tiruvallur", "Tiruvannamalai",
    "Tiruvarur", "Vellore", "Viluppuram", "Virudhunagar",
]

DOC_TYPE_PATTERNS = {
    "Income Certificate": [r"income\s+cert", r"income", r"annual\s+income"],
    "Birth Certificate": [r"birth\s+cert", r"birth", r"date\s+of\s+birth"],
    "Community Certificate": [r"community\s+cert", r"community", r"caste"],
    "Aadhaar Card": [r"aadhaar", r"aadhar", r"uidai"],
    "Student Permission Form": [r"student\s+permission", r"permission\s+form", r"permission", r"student\s+form"],
}


@dataclass
class AssistantResponse:
    """Structured response from the AI Government Record Assistant."""

    query: str
    intent: str
    generated_sql: str
    answer: str
    count: int
    records: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    is_count_query: bool = False


class SQLSafetyError(Exception):
    """Raised when an unsafe or non-read-only query is detected."""


def validate_safe_sql(sql: str) -> None:
    """Ensure that the SQL statement is strictly read-only and safe."""
    cleaned = sql.strip().upper()
    if not cleaned.startswith("SELECT"):
        raise SQLSafetyError("Only SELECT queries are permitted for AI search.")

    forbidden_keywords = [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
        "TRUNCATE", "REPLACE INTO", "EXEC", "EXECUTE", "ATTACH", "DETACH",
        "PRAGMA", "VACUUM", "--", ";",
    ]
    for kw in forbidden_keywords:
        if kw in ["--", ";"]:
            if kw in cleaned:
                raise SQLSafetyError(f"Unsafe SQL character detected: {kw}")
        else:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, cleaned):
                raise SQLSafetyError(f"Unsafe SQL keyword detected: {kw}")


def extract_entities(query: str) -> Dict[str, Any]:
    """Extract recognized domain entities from natural language query."""
    q_lower = query.lower()
    entities: Dict[str, Any] = {}

    # 1. Document Type
    for doc_type, patterns in DOC_TYPE_PATTERNS.items():
        if any(re.search(r"\b" + pat + r"\b", q_lower) for pat in patterns):
            entities["document_type"] = doc_type
            break

    # 2. District
    for dist in TAMIL_NADU_DISTRICTS:
        if re.search(r"\b" + re.escape(dist.lower()) + r"\b", q_lower):
            entities["district"] = dist
            break

    # 3. Certificate / Roll / Aadhaar numbers
    cert_match = re.search(r"\b(TN-[A-Za-z0-9\-]+)\b", query, re.I)
    if cert_match:
        entities["certificate_number"] = cert_match.group(1).upper()

    roll_match = re.search(r"\b(\d{2}[A-Za-z]{2,4}[A-Za-z0-9]{2,4})\b", query)
    if roll_match:
        entities["roll_number"] = roll_match.group(1).upper()

    aadhaar_match = re.search(r"\b(\d{4}\s?\d{4}\s?\d{4})\b", query)
    if aadhaar_match:
        entities["aadhaar_number"] = aadhaar_match.group(1)

    # 4. Year / Date
    year_match = re.search(r"\b(20\d{2})\b", query)
    if year_match:
        entities["year"] = year_match.group(1)

    # 5. Citizen Name
    COMMAND_WORDS = {
        "search", "show", "find", "list", "get", "how", "what", "check", "tell", "view",
        "income", "birth", "community", "aadhaar", "student", "permission", "form",
        "certificate", "card", "records", "documents", "document", "record", "all",
        "roll", "number", "date", "year", "district"
    }

    # First check for explicit name indicator phrases
    m_name = re.search(r"(?:for|named|citizen|student|applicant|person|name\s*(?:is|:)?)\s+([A-Za-z]+(?:\s+[A-Za-z\.]*)?)", query, re.I)
    if m_name:
        candidate = m_name.group(1).strip()
        if candidate.lower() not in COMMAND_WORDS and candidate.lower() not in [d.lower() for d in TAMIL_NADU_DISTRICTS]:
            entities["name"] = candidate
    else:
        # Check for 2-token person name (e.g., 'Gopal N', 'Senthil Nathan', 'Boopathy G')
        m_two_word = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+|\s+[A-Z]\.?))\b", query)
        if m_two_word:
            candidate = m_two_word.group(1).strip()
            first_word = candidate.split()[0].lower()
            if first_word not in COMMAND_WORDS and first_word not in [d.lower() for d in TAMIL_NADU_DISTRICTS]:
                entities["name"] = candidate

    return entities


def build_sql_from_query(query: str, entities: Dict[str, Any]) -> Tuple[str, List[Any], str, bool]:
    """Translate natural language query and entities into safe parameterized SQL.
    
    Returns: (sql_query, sql_params, intent, is_count)
    """
    q_lower = query.lower()

    # Intent A: Count / Aggregation
    is_count = any(k in q_lower for k in ["how many", "count", "total", "number of"])

    # Intent B: Duplicate Logs
    if any(k in q_lower for k in ["duplicate", "blocked", "prevented", "rejected"]):
        if is_count:
            return "SELECT COUNT(*) FROM duplicate_logs", [], "count_duplicates", True
        return (
            "SELECT id, filename, reason, detected_at "
            "FROM duplicate_logs ORDER BY id DESC LIMIT 10",
            [],
            "search_duplicates",
            False,
        )

    # Intent C: Standard Government Documents Query
    base_select = "SELECT COUNT(*) FROM government_documents" if is_count else (
        "SELECT id, document_type, citizen_name, certificate_number, aadhaar_number, "
        "dob, district, issue_date, upload_date, file_path, extra_fields "
        "FROM government_documents"
    )

    conditions: List[str] = []
    params: List[Any] = []

    if "document_type" in entities:
        conditions.append("document_type = ?")
        params.append(entities["document_type"])

    if "district" in entities:
        conditions.append("LOWER(district) LIKE ?")
        params.append(f"%{entities['district'].lower()}%")

    if "certificate_number" in entities:
        conditions.append("(certificate_number = ? OR extra_fields LIKE ?)")
        params.extend([entities["certificate_number"], f"%{entities['certificate_number']}%"])

    if "roll_number" in entities:
        conditions.append("(certificate_number = ? OR extra_fields LIKE ?)")
        params.extend([entities["roll_number"], f"%{entities['roll_number']}%"])

    if "aadhaar_number" in entities:
        cleaned_aadhaar = entities["aadhaar_number"].replace(" ", "")
        conditions.append("(REPLACE(aadhaar_number, ' ', '') LIKE ? OR extra_fields LIKE ?)")
        params.extend([f"%{cleaned_aadhaar}%", f"%{cleaned_aadhaar}%"])

    if "year" in entities:
        conditions.append("(issue_date LIKE ? OR upload_date LIKE ?)")
        params.extend([f"%{entities['year']}%", f"%{entities['year']}%"])

    if "name" in entities:
        conditions.append("LOWER(citizen_name) LIKE ?")
        params.append(f"%{entities['name'].lower()}%")

    # If no structured entities found and this is NOT a general count query, perform free-text search
    COMMON_STOP_WORDS = {
        "the", "all", "and", "for", "with", "show", "find", "list", "get", "give",
        "records", "record", "documents", "document", "how", "many", "there", "are",
        "total", "digitized", "count", "please", "me", "tell", "what", "is", "of", "in",
        "from", "at", "to", "a", "an", "any", "some"
    }

    if not conditions and not is_count:
        words = [w for w in re.findall(r"\w+", q_lower) if len(w) > 2 and w not in COMMON_STOP_WORDS]
        if words:
            text_conditions = []
            for word in words[:3]:
                text_conditions.append(
                    "(LOWER(citizen_name) LIKE ? OR LOWER(district) LIKE ? OR "
                    "LOWER(document_type) LIKE ? OR LOWER(certificate_number) LIKE ? OR "
                    "LOWER(ocr_text) LIKE ? OR LOWER(extra_fields) LIKE ?)"
                )
                params.extend([f"%{word}%"] * 6)
            conditions.append("(" + " AND ".join(text_conditions) + ")")

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_clause = "" if is_count else " ORDER BY id DESC LIMIT 15"
    full_sql = base_select + where_clause + order_clause
    intent = "count_records" if is_count else "search_records"

    return full_sql, params, intent, is_count


def generate_natural_answer(
    query: str,
    intent: str,
    is_count: bool,
    records: List[Dict[str, Any]],
    count: int,
    entities: Dict[str, Any],
) -> str:
    """Synthesize a human-like, conversational answer from the query results."""
    # 1. Count answers
    if is_count:
        if intent == "count_duplicates":
            return f"The deduplication engine has prevented {count} duplicate document upload attempt(s) so far."
        if entities.get("document_type"):
            return f"Found {count} registered {entities['document_type']}(s) in the database."
        if entities.get("district"):
            return f"Found {count} digitized record(s) from {entities['district']} district."
        return f"There are currently {count} digitized government document record(s) in the platform."

    # 2. Duplicate log search
    if intent == "search_duplicates":
        if count == 0:
            return "No duplicate upload attempts have been recorded. All documents uploaded are unique."
        return f"Retrieved {count} prevented duplicate attempt(s) from the audit log."

    # 3. Document search answers
    if count == 0:
        details = []
        if entities.get("document_type"):
            details.append(f"type '{entities['document_type']}'")
        if entities.get("district"):
            details.append(f"district '{entities['district']}'")
        if entities.get("name"):
            details.append(f"name '{entities['name']}'")
        filter_desc = " with " + ", ".join(details) if details else ""
        return f"No digitized records found{filter_desc}. Try searching by a different name, district, or certificate number."

    if count == 1:
        doc = records[0]
        name = doc.get("citizen_name") or "Citizen"
        doc_type = doc.get("document_type") or "Document"
        district = doc.get("district") or "Tamil Nadu"
        cert_no = doc.get("certificate_number") or doc.get("extra_fields", {}).get("Roll Number") or "N/A"
        date = doc.get("issue_date") or doc.get("upload_date") or ""
        date_str = f" issued on {date}" if date else ""
        return (
            f"Found 1 {doc_type} for {name} in {district} "
            f"(Certificate/ID: {cert_no}{date_str})."
        )

    # Multiple records
    types_found = list({r.get("document_type", "Document") for r in records})
    types_str = ", ".join(types_found[:2])
    return (
        f"Found {count} matching records ({types_str}). "
        f"You can inspect any record using the cards below."
    )


def generate_suggestions(records: List[Dict[str, Any]], count: int) -> List[str]:
    """Generate dynamic follow-up query suggestions."""
    suggestions = [
        "Show all income certificates",
        "Find records from Tiruppur",
        "How many documents are digitized?",
        "Check prevented duplicates",
        "List student permission forms",
    ]
    return suggestions[:4]


def process_assistant_query(database_path: str | Path, natural_query: str) -> AssistantResponse:
    """Process a natural language query end-to-end against the SQLite database."""
    query = (natural_query or "").strip()
    if not query:
        return AssistantResponse(
            query="",
            intent="empty",
            generated_sql="",
            answer="Please type a question or choose a prompt to search government records.",
            count=0,
            suggestions=[
                "Show all income certificates",
                "How many documents are digitized?",
                "Find records in Tiruppur",
            ],
        )

    entities = extract_entities(query)
    sql, params, intent, is_count = build_sql_from_query(query, entities)

    # Validate read-only safety
    validate_safe_sql(sql)

    db_path = Path(database_path)
    if not db_path.exists():
        return AssistantResponse(
            query=query,
            intent=intent,
            generated_sql=sql,
            answer="Database file not found. Please upload documents first.",
            count=0,
            suggestions=generate_suggestions([], 0),
        )

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        if is_count:
            count = rows[0][0] if rows else 0
            records = []
        else:
            records = []
            for row in rows:
                rec = dict(row)
                if "extra_fields" in rec and isinstance(rec["extra_fields"], str):
                    try:
                        rec["extra_fields"] = json.loads(rec["extra_fields"])
                    except Exception:
                        rec["extra_fields"] = {}
                records.append(rec)
            count = len(records)

    except Exception as error:
        connection.close()
        return AssistantResponse(
            query=query,
            intent="error",
            generated_sql=sql,
            answer=f"Could not execute query: {error}",
            count=0,
            suggestions=generate_suggestions([], 0),
        )
    finally:
        connection.close()

    answer = generate_natural_answer(query, intent, is_count, records, count, entities)
    suggestions = generate_suggestions(records, count)

    # Format SQL string with parameter preview for transparency
    display_sql = sql
    if params:
        param_strs = [f"'{p}'" if isinstance(p, str) else str(p) for p in params]
        display_sql = f"{sql} /* bindings: {', '.join(param_strs)} */"

    return AssistantResponse(
        query=query,
        intent=intent,
        generated_sql=display_sql,
        answer=answer,
        count=count,
        records=records,
        suggestions=suggestions,
        is_count_query=is_count,
    )
