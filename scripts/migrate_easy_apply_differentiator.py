import sqlite3
import json

def migrate():
    conn = sqlite3.connect("logs/autobot.db")
    c = conn.cursor()

    # 1. Update RecruitBots AI jobs
    recruitbots_jobs = [
        ("4492817177", "AI Workflow Automation Engineer", "RecruitBots AI", "Bengaluru, Karnataka, India"),
        ("4492814458", "GenAI Python developer", "RecruitBots AI", "Bengaluru, Karnataka, India"),
    ]

    for job_id, title, company, location in recruitbots_jobs:
        # Check job in jobs table
        row = c.execute("SELECT id, raw_data FROM jobs WHERE stable_id = ?", (job_id,)).fetchone()
        if row:
            j_id, raw_str = row
            raw = json.loads(raw_str) if raw_str else {}
            raw["is_easy_apply"] = True
            raw["platform"] = "LinkedIn (Easy Apply)"
            raw["platform_category"] = "linkedin"
            raw["apply_type"] = "Easy Apply"
            clean_desc = f"Position: {title} at {company}. Location: {location}. In-app LinkedIn Easy Apply opportunity."
            c.execute(
                "UPDATE jobs SET description = ?, raw_data = ?, application_url = ? WHERE id = ?",
                (clean_desc, json.dumps(raw), f"https://www.linkedin.com/jobs/view/{job_id}/", j_id)
            )

        # Update in applications table
        c.execute(
            "UPDATE applications SET apply_type = 'easy_apply', url = ? WHERE job_id = ?",
            (f"https://www.linkedin.com/jobs/view/{job_id}/", job_id)
        )

    # 2. Sync all applications that have apply_type = 'easy_apply' to have raw_data with is_easy_apply = True
    c.execute("""
        SELECT j.id, j.stable_id, j.raw_data 
        FROM jobs j
        JOIN applications a ON (j.stable_id = a.job_id OR CAST(j.id AS TEXT) = a.job_id)
        WHERE a.apply_type = 'easy_apply'
    """)
    rows = c.fetchall()
    for j_id, s_id, raw_str in rows:
        raw = json.loads(raw_str) if raw_str else {}
        if not raw.get("is_easy_apply") or raw.get("platform") != "LinkedIn (Easy Apply)":
            raw["is_easy_apply"] = True
            raw["platform"] = "LinkedIn (Easy Apply)"
            raw["platform_category"] = "linkedin"
            raw["apply_type"] = "Easy Apply"
            c.execute("UPDATE jobs SET raw_data = ? WHERE id = ?", (json.dumps(raw), j_id))

    conn.commit()
    conn.close()
    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()
