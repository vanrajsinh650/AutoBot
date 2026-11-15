"""
Generates the comprehensive 60-pair evaluation dataset for AutoBot v2.3 matching quality.
Saves to data/benchmarks/matching_eval_dataset.json.
"""

import json
import os

pairs = []

# Helper to add pairs
def add_pair(pid, cat, resume_skills, resume_exp, resume_edu, pref_roles, pref_emp, pref_countries, pref_workplace,
             job_title, job_company, job_desc, job_emp, job_loc, job_country, job_remote,
             exp_elig, exp_score_min, exp_score_max, exp_disagree, notes):
    pairs.append({
        "pair_id": pid,
        "category": cat,
        "resume": {
            "full_name": f"Candidate {pid}",
            "technical_skills": resume_skills,
            "primary_skills": resume_skills[:4],
            "secondary_skills": resume_skills[4:],
            "experience": resume_exp,
            "education": resume_edu,
        },
        "preferences": {
            "target_roles": pref_roles,
            "employment_types": pref_emp,
            "eligible_countries": pref_countries,
            "work_arrangement": pref_workplace,
            "min_salary": 0.0,
            "min_fit_threshold": 60.0,
        },
        "job": {
            "stable_id": f"benchmark:{pid}",
            "title": job_title,
            "company": job_company,
            "description": job_desc,
            "employment_type": job_emp,
            "location": job_loc,
            "country": job_country,
            "is_remote": job_remote,
        },
        "expected_eligibility": exp_elig,
        "expected_score_range": [exp_score_min, exp_score_max],
        "expected_disagreement": exp_disagree,
        "notes": notes,
    })

# ── 1. EXACT MATCHES (10) ──────────────────────────────────────────────────────
exact_cases = [
    ("Python Backend", ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
     "Senior Python Backend Engineer", "Build scalable microservices in Python, FastAPI, and PostgreSQL with Docker.", 75.0, 100.0),
    ("AI / ML", ["Python", "PyTorch", "LLM", "LangChain", "Vector DB"],
     "Applied AI Engineer", "Design and deploy generative AI applications with Python, PyTorch, and LangChain.", 75.0, 100.0),
    ("Frontend React", ["React", "TypeScript", "Next.js", "Tailwind CSS", "HTML5"],
     "Senior Frontend Engineer", "Develop responsive web applications using React, TypeScript, and Next.js.", 75.0, 100.0),
    ("DevOps Cloud", ["Kubernetes", "Docker", "Terraform", "AWS", "CI/CD"],
     "Platform / DevOps Engineer", "Maintain cloud infrastructure on AWS using Kubernetes, Terraform, and CI/CD pipelines.", 75.0, 100.0),
    ("Data Engineer", ["Python", "SQL", "Apache Spark", "Snowflake", "dbt"],
     "Staff Data Engineer", "Build scalable batch and streaming pipelines using Python, SQL, Apache Spark, and Snowflake.", 75.0, 100.0),
    ("Full Stack JS", ["JavaScript", "TypeScript", "Node.js", "React", "PostgreSQL"],
     "Full Stack Engineer", "End-to-end web engineering using TypeScript, Node.js, React, and PostgreSQL.", 75.0, 100.0),
    ("Security AppSec", ["Python", "AppSec", "OAuth", "OWASP", "IAM"],
     "Application Security Engineer", "Perform vulnerability scanning, threat modeling, and secure IAM and OAuth implementations.", 75.0, 100.0),
    ("Go Microservices", ["Golang", "Kubernetes", "gRPC", "Docker", "PostgreSQL"],
     "Go Systems Engineer", "Develop high-throughput microservices using Golang, gRPC, and Kubernetes.", 75.0, 100.0),
    ("Android Kotlin", ["Kotlin", "Android SDK", "Jetpack Compose", "Coroutines", "Java"],
     "Senior Android Developer", "Build native mobile experiences using Kotlin, Jetpack Compose, and modern Android SDK.", 75.0, 100.0),
    ("Systems C++", ["C++", "Linux", "Multithreading", "Algorithms", "Git"],
     "Systems Software Engineer", "Low-latency systems development in modern C++ on Linux with multithreading.", 75.0, 100.0),
]

for idx, (label, skills, jtitle, jdesc, smin, smax) in enumerate(exact_cases, 1):
    add_pair(
        pid=f"exact_{idx:02d}",
        cat="exact_match",
        resume_skills=skills,
        resume_exp=[{"role": jtitle, "company": "Tech Corp", "years": 4.0, "bullets": [f"Architected systems with {skills[0]} and {skills[1]}."]}],
        resume_edu=[{"degree": "Bachelor of Science in Computer Science", "institution": "State University"}],
        pref_roles=[jtitle, "Software Engineer"],
        pref_emp=["full-time"],
        pref_countries=["United States", "India"],
        pref_workplace="remote",
        job_title=jtitle,
        job_company="Acme Corp",
        job_desc=f"{jdesc} Required skills: {', '.join(skills[:3])}. Preferred skills: {', '.join(skills[3:])}. 3+ years experience. Bachelor degree required.",
        job_emp="full-time",
        job_loc="Remote - US",
        job_country="United States",
        job_remote=True,
        exp_elig="ELIGIBLE",
        exp_score_min=smin,
        exp_score_max=smax,
        exp_disagree=False,
        notes=f"Strong direct alignment for {label}.",
    )

# ── 2. ABBREVIATIONS & ALIASES (10) ───────────────────────────────────────────
alias_cases = [
    ("k8s to Kubernetes", ["k8s", "docker"], "Cloud Engineer", "Requires Kubernetes container orchestration and docker.", 65.0, 100.0),
    ("py to Python", ["py", "fastapi"], "Backend Engineer", "Requires Python 3 and FastAPI development.", 65.0, 100.0),
    ("psql to PostgreSQL", ["psql", "python"], "Database Backend Dev", "Requires PostgreSQL database queries and Python.", 65.0, 100.0),
    ("ts to TypeScript", ["ts", "react"], "UI Engineer", "Requires TypeScript and React web development.", 65.0, 100.0),
    ("js to JavaScript", ["js", "html"], "Web Developer", "Requires JavaScript and modern web standards.", 65.0, 100.0),
    ("aws to Amazon Web Services", ["aws", "terraform"], "Infra Engineer", "Requires Amazon Web Services cloud and Terraform.", 65.0, 100.0),
    ("gcp to Google Cloud", ["gcp", "kubernetes"], "SRE", "Requires Google Cloud Platform and Kubernetes.", 65.0, 100.0),
    ("mongo to MongoDB", ["mongo", "nodejs"], "Node Engineer", "Requires MongoDB document store and NodeJS.", 65.0, 100.0),
    ("reactjs to React", ["reactjs", "typescript"], "Frontend Dev", "Requires React and TypeScript components.", 65.0, 100.0),
    ("cicd to CI/CD", ["cicd", "docker"], "Build Engineer", "Requires CI/CD deployment automation and Docker.", 65.0, 100.0),
]

for idx, (label, skills, jtitle, jdesc, smin, smax) in enumerate(alias_cases, 1):
    add_pair(
        pid=f"alias_{idx:02d}",
        cat="abbreviations_and_aliases",
        resume_skills=skills,
        resume_exp=[{"role": jtitle, "company": "Cloud Co", "years": 3.0, "bullets": [f"Implemented {skills[0]} solutions."]}],
        resume_edu=[{"degree": "Bachelor of Technology", "institution": "Tech Institute"}],
        pref_roles=[jtitle, "Software Engineer"],
        pref_emp=["full-time"],
        pref_countries=["United States", "India"],
        pref_workplace="remote",
        job_title=jtitle,
        job_company="Alias Corp",
        job_desc=f"{jdesc} Required skills: {jdesc.split('Requires ')[1].split('.')[0]}. 2+ years of experience.",
        job_emp="full-time",
        job_loc="Remote",
        job_country="United States",
        job_remote=True,
        exp_elig="ELIGIBLE",
        exp_score_min=smin,
        exp_score_max=smax,
        exp_disagree=False,
        notes=f"Verify alias normalization handles {label}.",
    )

# ── 3. NEGATIONS & EXCLUSIONS (10) ────────────────────────────────────────────
negation_cases = [
    ("No Python", ["Python", "Django"], "Go Microservices Developer",
     "We write high performance services in Go. No Python or Django required. Must know Golang and gRPC.", 0.0, 45.0),
    ("Without Java", ["Java", "Spring Boot"], "Modern Rust Engineer",
     "Greenfield Rust engineering. Without Java or legacy JVM frameworks. Must have Rust experience.", 0.0, 45.0),
    ("React not needed", ["React", "Redux"], "Native iOS Engineer",
     "Native Swift development. React is not required or needed. Only Swift and UIKit.", 0.0, 45.0),
    ("Candidate must not use PHP", ["PHP", "Laravel"], "Node.js Backend Dev",
     "Modern TypeScript APIs. Candidates must not use PHP. TypeScript and Express required.", 0.0, 45.0),
    ("Never use Docker", ["Docker", "Kubernetes"], "Embedded Bare Metal Dev",
     "Firmware programming on ARM chips. We never use Docker or containerization. C and assembly required.", 0.0, 45.0),
    ("No SQL needed", ["SQL", "PostgreSQL"], "Vector DB Architect",
     "Pure semantic search engine. No SQL or relational databases needed. Graph neural nets required.", 0.0, 45.0),
    ("No Flutter", ["Flutter", "Dart"], "Native Android Dev",
     "Native Android apps. No Flutter or cross-platform tools. Kotlin required.", 0.0, 45.0),
    ("Python is not needed", ["Python"], "Ruby on Rails Senior Engineer",
     "Legacy Rails stack. Python is not needed. Ruby and Rails required.", 0.0, 45.0),
    ("Kubernetes strictly not used", ["Kubernetes"], "Serverless Architect",
     "Pure AWS Lambda architectures. Kubernetes is strictly not used here. Serverless framework required.", 0.0, 45.0),
    ("No AWS required", ["AWS"], "Azure Enterprise Consultant",
     "Microsoft ecosystem. No AWS experience required; we are exclusively Azure.", 0.0, 45.0),
]

for idx, (label, skills, jtitle, jdesc, smin, smax) in enumerate(negation_cases, 1):
    add_pair(
        pid=f"neg_{idx:02d}",
        cat="negations_and_not_required",
        resume_skills=skills,
        resume_exp=[{"role": "Developer", "company": "Legacy Corp", "years": 3.0, "bullets": [f"Worked with {skills[0]}."]}],
        resume_edu=[{"degree": "Bachelor Degree", "institution": "University"}],
        pref_roles=[jtitle],
        pref_emp=["full-time"],
        pref_countries=["United States"],
        pref_workplace="remote",
        job_title=jtitle,
        job_company="Negation Inc",
        job_desc=jdesc,
        job_emp="full-time",
        job_loc="Remote",
        job_country="United States",
        job_remote=True,
        exp_elig="ELIGIBLE",
        exp_score_min=smin,
        exp_score_max=smax,
        exp_disagree=False,
        notes=f"Negation check: ensure negated skills in {label} do not inflate score.",
    )

# ── 4. MANDATORY REQUIREMENTS MISMATCH (10) ───────────────────────────────────
mismatch_cases = [
    ("Country Mismatch US vs India", ["Python", "FastAPI"], "US On-Site Engineer",
     "Must work in New York City office. United States work authorization required.", ["India"], "INELIGIBLE"),
    ("Country Mismatch Germany vs US", ["Java", "Spring"], "Berlin On-Site Lead",
     "Work in Berlin office. Germany residency required.", ["United States"], "INELIGIBLE"),
    ("Country Mismatch Japan vs US", ["Python"], "Tokyo Backend Dev",
     "Work on-site in Tokyo. Japan work visa required.", ["United States"], "INELIGIBLE"),
    ("Experience 10+ yrs vs 1 yr", ["React"], "Staff Principal Architect",
     "Requires minimum 10+ years of professional engineering experience.", ["India"], "INELIGIBLE"),
    ("Employment Internship vs Senior", ["Python"], "Senior Staff Lead",
     "Full-time senior leadership role. 8+ years experience.", ["United States"], "INELIGIBLE"),
    ("Workplace On-Site Japan vs US Candidate", ["Go", "Kubernetes"], "Tokyo On-Site Engineer",
     "Strict 5 days on-site Tokyo office. No remote permitted.", ["United States"], "INELIGIBLE"),
    ("Full-Time vs Unpaid Volunteer", ["HTML", "CSS"], "Nonprofit Volunteer",
     "Unpaid part-time volunteer position, 5 hours weekly.", ["India"], "INELIGIBLE"),
    ("Country Mismatch Canada vs US", ["C++", "Linux"], "Toronto Systems Engineer",
     "Toronto office. Canadian permanent residency required.", ["United States"], "INELIGIBLE"),
    ("Country Mismatch UK vs US", ["Python", "SQL"], "London Data Analyst",
     "London office on-site. UK work authorization required.", ["United States"], "INELIGIBLE"),
    ("Country Mismatch Australia vs India", ["Python"], "Sydney FinTech Architect",
     "Sydney office on-site. Australian citizenship required.", ["India"], "INELIGIBLE"),
]

for idx, (label, skills, jtitle, jdesc, countries, exp_elig) in enumerate(mismatch_cases, 1):
    emp_pref = ["internship"] if "Internship" in label else ["full-time"]
    work_pref = "remote" if "Remote" in label else "on-site"
    if "Germany" in label:
        j_country = "Germany"
        j_loc = "Berlin, Germany"
    elif "Japan" in label or "Tokyo" in label:
        j_country = "Japan"
        j_loc = "Tokyo, Japan"
    elif "Canada" in label or "Toronto" in label:
        j_country = "Canada"
        j_loc = "Toronto, Canada"
    elif "UK" in label or "London" in label:
        j_country = "United Kingdom"
        j_loc = "London, UK"
    elif "Australia" in label or "Sydney" in label:
        j_country = "Australia"
        j_loc = "Sydney, Australia"
    else:
        j_country = "United States"
        j_loc = "New York, NY"

    add_pair(
        pid=f"mismatch_{idx:02d}",
        cat="mandatory_requirements_mismatch",
        resume_skills=skills,
        resume_exp=[{"role": "Engineer", "company": "Co", "years": 1.0, "bullets": ["Built applications."]}],
        resume_edu=[{"degree": "Bachelor of Science", "institution": "College"}],
        pref_roles=[jtitle],
        pref_emp=emp_pref,
        pref_countries=countries,
        pref_workplace=work_pref,
        job_title=jtitle,
        job_company="Strict Corp",
        job_desc=f"{jdesc} Required skills: {', '.join(skills)}.",
        job_emp="full-time",
        job_loc=j_loc,
        job_country=j_country,
        job_remote=False,
        exp_elig=exp_elig,
        exp_score_min=0.0,
        exp_score_max=85.0,
        exp_disagree=True if exp_elig == "INELIGIBLE" else False,
        notes=f"Mandatory requirement failure: {label}.",
    )

# ── 5. MISLEADING JOB DESCRIPTIONS (10) ─────────────────────────────────────────
misleading_cases = [
    ("AI Title Sales Job", "AI Solutions Engineer", "Cold-calling outbound telephone sales representative selling CRM subscriptions. 100 calls daily.", 0.0, 35.0),
    ("ML Title Data Entry", "Machine Learning Associate", "Manual data entry typing numbers from scanned paper invoices into Excel spreadsheets.", 0.0, 35.0),
    ("Full Stack Title WordPress", "Full Stack Ninja", "Install off-the-shelf WordPress themes and write promotional marketing copy.", 0.0, 35.0),
    ("Cloud Architect Title Call Center", "Cloud Solutions Architect", "Inbound customer support call center agent answering billing and password reset calls.", 0.0, 35.0),
    ("Blockchain Dev Title Telegram Shiller", "Lead Web3 Developer", "Post promotional memes and hype messages in Telegram and Discord community groups.", 0.0, 35.0),
    ("Python Dev Title Elementary Tutor", "Python Software Engineer", "Baby-sit and teach 8-year-old elementary school children basic Scratch and turtle graphics.", 0.0, 35.0),
    ("DevOps Title Cable Repair", "DevOps Infrastructure Specialist", "Replace office printer paper and untangle HDMI projector cables in meeting rooms.", 0.0, 35.0),
    ("Data Scientist Title Copy Paste", "Senior Data Scientist", "Copy and paste quarterly revenue figures from PDF emails into Google Sheets.", 0.0, 35.0),
    ("Cybersecurity Title Door Guard", "Cybersecurity Operations Analyst", "Physical lobby door guard checking badges and visitor IDs at security turnstile.", 0.0, 35.0),
    ("Mobile Dev Title Survey Taker", "Mobile React Specialist", "Walk door-to-door in residential neighborhoods with an iPad asking paper surveys.", 0.0, 35.0),
]

for idx, (label, jtitle, jdesc, smin, smax) in enumerate(misleading_cases, 1):
    skills = ["Python", "FastAPI", "Docker", "PostgreSQL", "React"]
    add_pair(
        pid=f"mislead_{idx:02d}",
        cat="misleading_job_descriptions",
        resume_skills=skills,
        resume_exp=[{"role": "Senior Engineer", "company": "Software Co", "years": 5.0, "bullets": ["Built cloud microservices."]}],
        resume_edu=[{"degree": "Bachelor of Science", "institution": "Tech University"}],
        pref_roles=[jtitle, "Software Engineer"],
        pref_emp=["full-time"],
        pref_countries=["United States"],
        pref_workplace="remote",
        job_title=jtitle,
        job_company="Shady Corp",
        job_desc=jdesc,
        job_emp="full-time",
        job_loc="Remote",
        job_country="United States",
        job_remote=True,
        exp_elig="ELIGIBLE",
        exp_score_min=smin,
        exp_score_max=smax,
        exp_disagree=False,
        notes=f"Misleading title detection: {label} has low actual technical requirement overlap.",
    )

# ── 6. HIGH FIT BUT INELIGIBLE (DISAGREEMENT CASES) (10) ───────────────────────
disagreement_cases = [
    ("US Citizen Only vs India Candidate", ["Python", "PyTorch", "FastAPI", "PostgreSQL", "Docker"],
     "Staff AI Engineer", "Build generative AI systems in Python, PyTorch, and FastAPI.", "United States", ["India"]),
    ("UK Gov Clearance vs Canada Candidate", ["Kubernetes", "Terraform", "AWS", "Docker", "CI/CD"],
     "Platform Architect", "Lead Kubernetes infrastructure on AWS using Terraform.", "United Kingdom", ["Canada"]),
    ("Germany On-Site vs US Candidate", ["React", "TypeScript", "Next.js", "Node.js"],
     "Lead Frontend Dev", "Develop web UI in React and TypeScript. 100% on-site Munich.", "Germany", ["United States"]),
    ("Staff Exec vs Candidate Internship", ["Python", "Go", "Docker", "PostgreSQL"],
     "Principal Engineering Director", "Direct 50 engineers. Requires 12+ years experience.", "United States", ["United States"]),
    ("Singapore On-Site vs Remote Only", ["Java", "Spring Boot", "Microservices", "Kafka"],
     "Senior Java Backend Engineer", "Build banking microservices in Java and Kafka. Must relocate to Singapore.", "Singapore", ["United States"]),
    ("France Citizen Only vs US Candidate", ["C++", "Linux", "gRPC", "Docker"],
     "High Performance C++ Dev", "Develop low latency trading platform in Paris. EU citizens only.", "France", ["United States"]),
    ("Active DoD Secret vs Foreign Candidate", ["Rust", "Linux", "Security", "Networking"],
     "Defense Systems Programmer", "Firmware security in Rust. Active US DoD Secret clearance strictly required. On-site Maryland.", "United States", ["India"]),
    ("Australia On-Site vs Remote Pref", ["Python", "SQL", "Spark", "Snowflake"],
     "Data Platform Lead", "Lead data warehouse in Sydney on-site 5 days a week.", "Australia", ["United States"]),
    ("Japan Fluent vs English Only", ["Ruby", "Rails", "PostgreSQL", "Docker"],
     "Senior Rails Developer", "Tokyo web service. Fluent bilingual Japanese JLPT N1 mandatory.", "Japan", ["United States"]),
    ("Switzerland On-Site vs India Candidate", ["TypeScript", "React", "GraphQL", "Node.js"],
     "Full Stack Architect", "Zurich engineering hub. Swiss work permit required.", "Switzerland", ["India"]),
]

for idx, (label, skills, jtitle, jdesc, jcountry, ccountries) in enumerate(disagreement_cases, 1):
    emp_pref = ["internship"] if "Internship" in label else ["full-time"]
    add_pair(
        pid=f"disagree_{idx:02d}",
        cat="eligibility_fit_disagreement",
        resume_skills=skills,
        resume_exp=[{"role": jtitle, "company": "Top Tier Tech", "years": 6.0, "bullets": [f"Architected {skills[0]} and {skills[1]} systems."]}],
        resume_edu=[{"degree": "Master of Computer Science", "institution": "Elite University"}],
        pref_roles=[jtitle],
        pref_emp=emp_pref,
        pref_countries=ccountries,
        pref_workplace="remote",
        job_title=jtitle,
        job_company="Global Corp",
        job_desc=f"{jdesc} Required skills: {', '.join(skills[:3])}. Preferred skills: {', '.join(skills[3:])}. 5+ years experience.",
        job_emp="full-time",
        job_loc=f"On-Site {jcountry}",
        job_country=jcountry,
        job_remote=False,
        exp_elig="INELIGIBLE",
        exp_score_min=65.0,  # Technical fit is high!
        exp_score_max=100.0,
        exp_disagree=True,   # Disagreement: High technical fit, but candidate cannot legally or operationally take the job!
        notes=f"Disagreement case: {label}. High technical qualification, but strictly INELIGIBLE.",
    )

output_path = "/home/vanrajsinh/Projects/AutoBot/data/benchmarks/matching_eval_dataset.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(pairs, f, indent=2)

print(f"Generated {len(pairs)} curated benchmark pairs in {output_path}")
