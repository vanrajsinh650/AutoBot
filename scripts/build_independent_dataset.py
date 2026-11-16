"""
Build the Independent Human-Labeled Ground-Truth Matching Evaluation Dataset for AutoBot v2.3.1.
Saves to data/benchmarks/independent_eval_dataset.json.

This evaluation suite is strictly separate from the development fixtures (matching_eval_dataset.json).
It features authentic candidate profiles, diverse career transitions, realistic ATS postings with
ambiguous language, incomplete profiles, subtle negations, hard mandatory gates, and location conflicts.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any

def create_pair(
    pair_id: str,
    category: str,
    candidate_name: str,
    headline: str,
    skills: List[str],
    experience: List[Dict[str, Any]],
    education: List[Dict[str, str]],
    target_roles: List[str],
    pref_emp: List[str],
    pref_countries: List[str],
    pref_workplace: str,
    job_title: str,
    job_company: str,
    job_desc: str,
    job_emp: str,
    job_loc: str,
    job_country: str,
    job_remote: bool,
    expected_eligibility: str,
    expected_relevance_grade: int,  # 0 = Irrelevant, 1 = Marginal/Partial, 2 = Good, 3 = Excellent
    expected_fit_tier: str,         # HIGH (>=70), MID (50-69), LOW (<50)
    is_location_conflict: bool,
    human_notes: str,
) -> Dict[str, Any]:
    return {
        "pair_id": pair_id,
        "category": category,
        "resume": {
            "full_name": candidate_name,
            "headline": headline,
            "technical_skills": skills,
            "primary_skills": skills[:4],
            "secondary_skills": skills[4:],
            "experience": experience,
            "education": education,
        },
        "preferences": {
            "target_roles": target_roles,
            "employment_types": pref_emp,
            "eligible_countries": pref_countries,
            "work_arrangement": pref_workplace,
            "min_salary": 0.0,
            "min_fit_threshold": 60.0,
        },
        "job": {
            "stable_id": f"independent:{pair_id}",
            "title": job_title,
            "company": job_company,
            "description": job_desc,
            "employment_type": job_emp,
            "location": job_loc,
            "country": job_country,
            "is_remote": job_remote,
        },
        "ground_truth": {
            "expected_eligibility": expected_eligibility,
            "expected_relevance_grade": expected_relevance_grade,
            "expected_fit_tier": expected_fit_tier,
            "is_location_conflict": is_location_conflict,
            "human_notes": human_notes,
        }
    }


def generate_independent_dataset() -> List[Dict[str, Any]]:
    pairs = []

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 1: REALISTIC HIGH FIT / DIRECT ALIGNMENT (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    high_fit_cases = [
        (
            "indep_high_01", "realistic_high_fit", "Elena Rostova", "Senior Python & Distributed Systems Engineer",
            ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "Kubernetes", "gRPC", "Kafka"],
            [
                {"role": "Senior Backend Engineer", "company": "Nexure Cloud", "years": 4.5, "bullets": ["Architected distributed microservices in Python and FastAPI handling 45k RPM.", "Optimized PostgreSQL query latency with Redis caching and partitioning.", "Orchestrated container workloads using Kubernetes and Docker."]},
                {"role": "Software Engineer", "company": "Datamesh Inc", "years": 2.5, "bullets": ["Developed event-driven data streaming pipelines with Kafka and Python.", "Integrated RESTful APIs and gRPC endpoints."]}
            ],
            [{"degree": "B.S. in Computer Science", "institution": "University of Washington"}],
            ["Senior Python Engineer", "Backend Software Engineer"], ["full-time"], ["United States"], "remote",
            "Senior Backend Engineer (Python / Distributed Systems)", "Aurora Networks",
            "Aurora Networks is hiring a Senior Backend Engineer to scale our core event processing platform. You will build and maintain resilient microservices in Python using FastAPI, PostgreSQL, Redis, and Kubernetes. We require 4+ years of backend engineering experience with production Python services and a Bachelor's degree in Computer Science. Knowledge of Kafka and Docker is highly desirable. This is a 100% remote US position.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Candidate has direct technical, experience, and role alignment."
        ),
        (
            "indep_high_02", "realistic_high_fit", "Marcus Vance", "Lead Frontend & Design Systems Engineer",
            ["TypeScript", "React", "Next.js", "Tailwind CSS", "GraphQL", "Jest", "Cypress", "Web Vitals"],
            [
                {"role": "Staff Frontend Engineer", "company": "VividUI", "years": 5.0, "bullets": ["Built enterprise design system used by 40+ engineering squads with React and Tailwind CSS.", "Engineered Next.js server-rendered applications achieving 99+ Core Web Vitals.", "Authored comprehensive unit and E2E test suites in Jest and Cypress."]}
            ],
            [{"degree": "Bachelor of Software Engineering", "institution": "Georgia Tech"}],
            ["Lead Frontend Engineer", "Staff Frontend Engineer", "Senior React Developer"], ["full-time"], ["United States"], "remote",
            "Senior Staff Frontend Engineer (Design Systems)", "Loomis Tech",
            "We are seeking an experienced Frontend Engineer with deep mastery of TypeScript, React, Next.js, and design tokens. You will spearhead our component library and front-of-the-frontend architecture. Required: 5+ years building modern web applications with React and TypeScript, Bachelor's degree, and experience with automated testing (Jest/Cypress).",
            "full-time", "San Francisco, CA / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Complete stack match with proven design system leadership."
        ),
        (
            "indep_high_03", "realistic_high_fit", "Aarav Patel", "Staff Cloud Infrastructure & SRE",
            ["Kubernetes", "Terraform", "AWS", "Docker", "Linux", "Prometheus", "CI/CD", "Golang", "Helm"],
            [
                {"role": "Principal SRE", "company": "Fintech Global", "years": 6.0, "bullets": ["Maintained multi-region AWS EKS clusters with Terraform and Helm.", "Automated zero-downtime CI/CD pipelines with GitHub Actions.", "Engineered observability stacks using Prometheus and Grafana."]}
            ],
            [{"degree": "B.Tech in Information Technology", "institution": "IIT Bombay"}],
            ["Site Reliability Engineer", "Platform Engineer", "DevOps Architect"], ["full-time"], ["India", "United States"], "remote",
            "Staff Site Reliability Engineer (Platform / AWS)", "Stripe Technologies",
            "Join our Infrastructure Platform team to manage scalable AWS infrastructure. Minimum 5+ years experience with Kubernetes, Terraform, AWS, Docker, and Linux. You will design automated CI/CD deployment pipelines, improve system reliability, and write tooling in Golang.",
            "full-time", "Remote - Global", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Exemplary match on cloud infrastructure, Kubernetes, and SRE responsibilities."
        ),
        (
            "indep_high_04", "realistic_high_fit", "Sofia Gomez", "Senior Applied AI & ML Engineer",
            ["Python", "PyTorch", "LLM", "LangChain", "Vector DB", "Transformers", "FastAPI", "Docker"],
            [
                {"role": "Applied AI Engineer", "company": "Cognitive Agents", "years": 4.0, "bullets": ["Built production RAG pipelines integrating Qdrant vector databases, LangChain, and fine-tuned LLMs.", "Deployed latency-optimized model inference endpoints with FastAPI and PyTorch."]}
            ],
            [{"degree": "Master of Science in Machine Learning", "institution": "Carnegie Mellon University"}],
            ["Applied AI Engineer", "LLM Engineer", "Machine Learning Engineer"], ["full-time"], ["United States"], "remote",
            "Senior AI Engineer - Generative AI & Retrieval", "Anthropic Partner Lab",
            "We are seeking a Senior AI Engineer to build generative AI workflows and retrieval-augmented generation systems. Requirements: Master's or Bachelor's in CS/AI, 3+ years experience with Python, PyTorch, LangChain, and vector embeddings. FastAPI and Docker deployment experience required.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Target role and modern generative AI/RAG stack align perfectly."
        ),
        (
            "indep_high_05", "realistic_high_fit", "Liam O'Connor", "Senior Full Stack Engineer",
            ["TypeScript", "React", "Node.js", "PostgreSQL", "Express", "Docker", "REST", "Tailwind CSS"],
            [
                {"role": "Full Stack Developer", "company": "Belfast Cloud", "years": 4.0, "bullets": ["Developed full-stack web applications with React, TypeScript, and Node.js.", "Designed normalized PostgreSQL schemas and managed migrations."]}
            ],
            [{"degree": "B.Sc. in Computer Science", "institution": "Trinity College Dublin"}],
            ["Full Stack Engineer", "Senior Software Developer"], ["full-time"], ["Ireland", "United Kingdom"], "hybrid",
            "Senior Full Stack Developer", "Dublin Health Tech",
            "We need a Senior Full Stack Developer proficient in TypeScript, React, Node.js, and PostgreSQL to build healthcare portals. Candidates must possess 3+ years full-stack experience and a degree in Computer Science. Hybrid role based in Dublin.",
            "full-time", "Dublin, Ireland", "Ireland", False,
            "ELIGIBLE", 3, "HIGH", False, "Strong geographic, tech stack, and role fit."
        ),
        (
            "indep_high_06", "realistic_high_fit", "Chloe Dubois", "Senior iOS Mobile Developer",
            ["Swift", "iOS", "SwiftUI", "Combine", "CoreData", "Git", "REST", "XCTest"],
            [
                {"role": "Senior iOS Engineer", "company": "Luxe Apps", "years": 5.0, "bullets": ["Shipped top-rated iOS applications with SwiftUI and Swift.", "Implemented offline synchronization using CoreData."]}
            ],
            [{"degree": "B.S. in Computer Applications", "institution": "Sorbonne University"}],
            ["Senior iOS Engineer", "iOS Developer"], ["full-time"], ["France", "European Union"], "remote",
            "Senior iOS Engineer (Swift & SwiftUI)", "Qonto Fintech",
            "We are looking for a Senior iOS Developer to craft delightful financial mobile experiences. Requirements: 4+ years native iOS development with Swift and SwiftUI, solid grasp of Combine and REST APIs, and a degree in Computer Science or equivalent. Remote in France or EU.",
            "full-time", "Paris, France / Remote", "France", True,
            "ELIGIBLE", 3, "HIGH", False, "Native iOS stack and location align cleanly."
        ),
        (
            "indep_high_07", "realistic_high_fit", "Tariq Mansour", "Senior Data Engineer (Distributed Pipelines)",
            ["Python", "SQL", "Apache Spark", "Snowflake", "dbt", "Airflow", "Kafka", "AWS"],
            [
                {"role": "Lead Data Engineer", "company": "Retail Matrix", "years": 5.0, "bullets": ["Built enterprise lakehouse processing 5TB/day using Apache Spark, Snowflake, and dbt.", "Orchestrated complex DAG pipelines with Apache Airflow on AWS."]}
            ],
            [{"degree": "B.S. in Information Systems", "institution": "King Fahd University"}],
            ["Senior Data Engineer", "Lead Data Engineer"], ["full-time"], ["United States", "Canada"], "remote",
            "Staff Data Engineer (Snowflake & Spark)", "InstaData Corp",
            "Looking for a Data Engineer to own our modern data stack. Must have 4+ years of data engineering experience with Python, SQL, Apache Spark, Snowflake, and dbt. Airflow and AWS experience required. Degree in CS or related field.",
            "full-time", "Remote - North America", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Matches core data engineering stack directly."
        ),
        (
            "indep_high_08", "realistic_high_fit", "Ananya Sharma", "Senior Go Systems Engineer",
            ["Golang", "Kubernetes", "gRPC", "Docker", "PostgreSQL", "Linux", "Microservices", "Prometheus"],
            [
                {"role": "Systems Engineer", "company": "Scalenet", "years": 4.0, "bullets": ["Implemented high-throughput gRPC microservices in Golang.", "Deployed services to Kubernetes with Docker containers on Linux."]}
            ],
            [{"degree": "Bachelor of Technology in Computer Engineering", "institution": "NIT Karnataka"}],
            ["Go Engineer", "Backend Systems Developer"], ["full-time"], ["India"], "remote",
            "Senior Golang Backend Engineer", "Razorpay Labs",
            "We are hiring a Senior Backend Engineer to write high-concurrency payment services in Golang. You will build gRPC microservices on Kubernetes and Linux. 3+ years Go experience and Bachelor's degree required.",
            "full-time", "Bangalore, India / Remote", "India", True,
            "ELIGIBLE", 3, "HIGH", False, "Solid Golang, systems, and microservices alignment."
        ),
        (
            "indep_high_09", "realistic_high_fit", "Kenji Takahashi", "Application Security Engineer",
            ["Python", "AppSec", "OAuth", "OWASP", "IAM", "Linux", "Docker", "Security", "Git"],
            [
                {"role": "Security Engineer", "company": "CyberShield Tokyo", "years": 4.5, "bullets": ["Conducted OWASP vulnerability assessments and secure code reviews.", "Implemented OAuth 2.0 and IAM access controls for cloud applications."]}
            ],
            [{"degree": "B.S. in Cybersecurity", "institution": "Waseda University"}],
            ["Application Security Engineer", "Security Software Engineer"], ["full-time"], ["Japan", "United States"], "remote",
            "Application Security (AppSec) Engineer", "Fastly Global",
            "Fastly is seeking an AppSec Engineer. Responsibilities include threat modeling, vulnerability mitigation, and reviewing code against OWASP standards. Required: 3+ years experience with application security, Python, OAuth, IAM, and Linux. Bachelor's degree required.",
            "full-time", "Tokyo, Japan / Remote", "Japan", True,
            "ELIGIBLE", 3, "HIGH", False, "Target security role and specialized domain match."
        ),
        (
            "indep_high_10", "realistic_high_fit", "Devon Miller", "Senior DevOps & Platform Engineer",
            ["Terraform", "Kubernetes", "AWS", "Docker", "CI/CD", "Linux", "Python", "Bash"],
            [
                {"role": "DevOps Engineer", "company": "CloudForge", "years": 4.0, "bullets": ["Provisioned multi-account AWS infrastructure using modular Terraform.", "Managed automated CI/CD pipelines and Kubernetes container fleets."]}
            ],
            [{"degree": "B.S. in Computer Science", "institution": "Purdue University"}],
            ["DevOps Engineer", "Cloud Infrastructure Engineer"], ["full-time"], ["United States"], "remote",
            "Senior Cloud Platform Engineer (AWS & Terraform)", "Datadog",
            "Join our Platform Engineering group. Required: 4+ years of cloud infrastructure automation using Terraform, AWS, Docker, Kubernetes, and Linux. Strong scripting skills in Python or Bash required. Degree in CS or related field.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Flawless DevOps / Cloud platform alignment."
        ),
    ]

    for c in high_fit_cases:
        pairs.append(create_pair(*c))

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 2: CAREER TRANSITIONS & ADJACENT SHIFTS (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    transition_cases = [
        (
            "indep_trans_01", "career_transition", "Vikram Sen", "Senior Enterprise Java Developer transitioning to Go & Cloud",
            ["Java", "Spring Boot", "PostgreSQL", "Docker", "REST", "SQL", "Git", "Microservices"],
            [
                {"role": "Senior Java Developer", "company": "Enterprise Banking Systems", "years": 6.0, "bullets": ["Built mission-critical microservices in Java and Spring Boot with PostgreSQL.", "Collaborated on containerized deployments using Docker."]}
            ],
            [{"degree": "B.Tech in Computer Science", "institution": "Delhi University"}],
            ["Go Engineer", "Backend Software Engineer", "Systems Engineer"], ["full-time"], ["India", "United States"], "remote",
            "Go Backend Systems Engineer (Golang & gRPC)", "Finscale Labs",
            "Seeking a Backend Engineer to build scalable microservices in Golang. Required: 3+ years writing high-throughput services in Go, gRPC, and Kubernetes. Strong grasp of PostgreSQL and Docker required.",
            "full-time", "Remote - Global", "United States", True,
            "ELIGIBLE", 2, "MID", False, "Candidate has deep backend/microservices experience in Java, but lacks Go/gRPC."
        ),
        (
            "indep_trans_02", "career_transition", "Hannah Ross", "Data Analyst transitioning to Machine Learning Engineer",
            ["SQL", "Pandas", "Tableau", "Excel", "Data Analysis", "Statistics"],
            [
                {"role": "Senior Data Analyst", "company": "Analytics Partners", "years": 4.0, "bullets": ["Developed customer segmentation dashboards in Tableau.", "Authored SQL queries on multi-million row datasets."]}
            ],
            [{"degree": "B.S. in Mathematics & Statistics", "institution": "University of Michigan"}],
            ["Machine Learning Engineer", "Junior ML Engineer", "Data Scientist"], ["full-time"], ["United States"], "remote",
            "Machine Learning Engineer (PyTorch & Scikit-Learn)", "RetailPredict AI",
            "Looking for an ML Engineer. You will work on tabular prediction models and feature pipelines. Required: Python, PyTorch, Scikit-Learn, and Docker. Degree in Math, Stats, or CS required.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 2, "MID", False, "Partial match: strong data analysis and stats background, but missing PyTorch/ML engineering stack."
        ),
        (
            "indep_trans_03", "career_transition", "Mateo Silva", "Frontend Specialist expanding into Full Stack Node.js",
            ["React", "JavaScript", "HTML5", "CSS3", "Tailwind CSS"],
            [
                {"role": "Frontend Developer", "company": "PixelCraft Studios", "years": 3.5, "bullets": ["Developed user interfaces with React and CSS."]}
            ],
            [{"degree": "B.S. in Interactive Media", "institution": "University of Texas"}],
            ["Full Stack Engineer", "Frontend Engineer"], ["full-time"], ["United States"], "remote",
            "Full Stack Software Engineer (Node.js & PostgreSQL)", "Clearpath SaaS",
            "We are seeking a Full Stack Engineer. Responsibilities include building backend Node.js, Express, and PostgreSQL microservices, with React UI. 3+ years backend experience required.",
            "full-time", "Austin, TX / Remote", "United States", True,
            "ELIGIBLE", 2, "MID", False, "Frontend engineer lacking core backend Node/PostgreSQL required by posting."
        ),
        (
            "indep_trans_04", "career_transition", "Sunil Rao", "QA Automation Engineer transitioning to Backend Development",
            ["Python", "Selenium", "Pytest", "Git", "CI/CD"],
            [
                {"role": "Senior QA Automation Engineer", "company": "TestSphere", "years": 4.5, "bullets": ["Engineered automated test frameworks in Python and Pytest."]}
            ],
            [{"degree": "B.E. in Electronics & Communication", "institution": "Anna University"}],
            ["Backend Developer", "Software Development Engineer in Test", "Python Developer"], ["full-time"], ["India"], "remote",
            "Backend Software Engineer (FastAPI & PostgreSQL)", "Finflow India",
            "We are hiring a Python Software Engineer to build high-scale financial transaction APIs using FastAPI, PostgreSQL, Redis, and Docker. 3+ years backend production experience required.",
            "full-time", "Bangalore, India", "India", True,
            "ELIGIBLE", 2, "MID", False, "QA automation background transitioning into pure backend role; lacks DB/FastAPI production experience."
        ),
        (
            "indep_trans_05", "career_transition", "Miriam Al-Hassan", "IT Systems Administrator transitioning to DevOps Engineer",
            ["Linux", "Bash", "Networking", "Hardware", "Security"],
            [
                {"role": "Senior Systems Administrator", "company": "Oasis Enterprise IT", "years": 5.0, "bullets": ["Administered corporate Linux server fleets and enterprise networking."]}
            ],
            [{"degree": "B.S. in Computer Information Systems", "institution": "Ohio State University"}],
            ["DevOps Engineer", "Cloud Operations Engineer", "Systems Engineer"], ["full-time"], ["United States"], "remote",
            "Cloud DevOps Engineer (AWS & Terraform)", "Apex Media Cloud",
            "We are looking for a DevOps Engineer to automate our AWS cloud infrastructure using Terraform, Kubernetes, Docker, and CI/CD pipelines. 3+ years cloud infrastructure automation required.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 2, "MID", False, "Sysadmin transitioning to DevOps: strong OS/networking match, but lacks AWS/Terraform/K8s."
        ),
        (
            "indep_trans_06", "career_transition", "Carlos Mendez", "Embedded C Firmware Developer transitioning to Rust Systems",
            ["C", "Linux", "Multithreading", "ARM", "Algorithms"],
            [
                {"role": "Embedded Systems Engineer", "company": "MicroChip Core", "years": 4.0, "bullets": ["Developed low-level firmware in C on Linux."]}
            ],
            [{"degree": "B.S. in Electrical & Computer Engineering", "institution": "Madrid Polytechnic"}],
            ["Systems Software Engineer", "Rust Developer"], ["full-time"], ["European Union", "United States"], "remote",
            "Systems Software Engineer (Rust & Distributed Storage)", "Vector Core Labs",
            "Vector Core is building high-performance storage engines in Rust. Required: 3+ years writing production Rust, Tokio async, and distributed consensus. Degree in CS/ECE.",
            "full-time", "Remote - Worldwide", "United States", True,
            "ELIGIBLE", 2, "MID", False, "Embedded C engineer moving into Rust systems: strong fundamentals, lacks production Rust."
        ),
        (
            "indep_trans_07", "career_transition", "Zoe Jenkins", "Full Stack PHP/Laravel developer transitioning to TypeScript & Next.js",
            ["PHP", "Laravel", "MySQL", "JavaScript", "HTML5", "CSS3", "Git"],
            [
                {"role": "Web Application Developer", "company": "Agency 404", "years": 4.0, "bullets": ["Built commercial web applications with PHP, Laravel, and MySQL."]}
            ],
            [{"degree": "B.A. in Computer Arts", "institution": "Leeds Beckett University"}],
            ["Frontend Developer", "Full Stack Engineer"], ["full-time"], ["United Kingdom"], "remote",
            "React / Next.js / TypeScript Frontend Engineer", "Manchester FinApp",
            "Looking for a Frontend Engineer with deep TypeScript, Next.js, React, and GraphQL skills to craft customer portals. 3+ years production TypeScript experience required.",
            "full-time", "Remote - UK", "United Kingdom", True,
            "ELIGIBLE", 2, "MID", False, "PHP background with web fundamentals, but missing required Next.js and TypeScript."
        ),
        (
            "indep_trans_08", "career_transition", "Sergei Romanov", "Desktop C#/.NET Developer transitioning to Cloud Backend",
            ["C#", "SQL", "Git"],
            [
                {"role": "Senior Desktop Engineer", "company": "MedEquip Systems", "years": 5.0, "bullets": ["Built enterprise healthcare desktop applications in C# with SQL Server."]}
            ],
            [{"degree": "B.S. in Computer Science", "institution": "Saint Petersburg State"}],
            ["Cloud Backend Engineer", "Software Engineer"], ["full-time"], ["Germany", "European Union"], "hybrid",
            "Cloud Backend Engineer (Python, Docker & AWS)", "Berlin Cloud Health",
            "Join our backend engineering team building cloud services in Python, FastAPI, Docker, and AWS. 3+ years experience with cloud backend services and relational databases required.",
            "full-time", "Berlin, Germany", "Germany", False,
            "ELIGIBLE", 2, "MID", False, "C# desktop developer applying to Python/AWS cloud backend role."
        ),
        (
            "indep_trans_09", "career_transition", "Nadia Kouassi", "Mechanical Engineer transitioning to Software Engineering (Bootcamp)",
            ["Python", "Git", "HTML5"],
            [
                {"role": "CAD Engineer", "company": "AeroStruct", "years": 3.0, "bullets": ["Developed mathematical models and simulation automation scripts in Python."]}
            ],
            [{"degree": "B.S. in Mechanical Engineering", "institution": "McGill University"}],
            ["Junior Software Engineer", "Python Developer"], ["full-time"], ["Canada"], "remote",
            "Software Engineer - Cloud Platform (Go & Kubernetes)", "Montreal Cloud",
            "Seeking a Software Engineer to develop Kubernetes controllers in Golang. Required: 3+ years software engineering, Go, Kubernetes, and Docker. Degree in CS preferred.",
            "full-time", "Montreal, Canada / Remote", "Canada", True,
            "ELIGIBLE", 2, "MID", False, "Non-traditional background with basic scripting, applying to core Go/K8s platform role."
        ),
        (
            "indep_trans_10", "career_transition", "Lucas Becker", "Database Administrator (DBA) transitioning to Data Engineering",
            ["PostgreSQL", "MySQL", "SQL", "Linux", "Bash"],
            [
                {"role": "Senior DBA", "company": "InfraCore", "years": 6.0, "bullets": ["Administered high-availability PostgreSQL and MySQL clusters."]}
            ],
            [{"degree": "B.S. in Database Systems", "institution": "Munich Technical"}],
            ["Data Engineer", "Database Engineer"], ["full-time"], ["Germany"], "hybrid",
            "Big Data Platform Engineer (Spark & Snowflake)", "Munich Mobility Labs",
            "We are seeking an engineer to build big data pipelines using Apache Spark, Snowflake, Kafka, and dbt. 3+ years experience with distributed data processing required.",
            "full-time", "Munich, Germany", "Germany", False,
            "ELIGIBLE", 2, "MID", False, "Senior DBA fundamentals map to data, but lacks Spark, Snowflake, and Kafka."
        ),
    ]

    for c in transition_cases:
        pairs.append(create_pair(*c))

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 3: AMBIGUOUS DESCRIPTIONS & MISLEADING TITLES (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    ambiguous_cases = [
        (
            "indep_ambig_01", "ambiguous_descriptions", "Arthur Dent", "Python Data Specialist",
            ["Python", "Pandas", "SQL", "Tableau", "Excel", "Data Analysis"],
            [{"role": "Data Analyst", "company": "Megadodo", "years": 3.0, "bullets": ["Created customer dashboards and data summaries in Python and Excel."]}],
            [{"degree": "B.A. in Economics", "institution": "Oxford"}],
            ["Data Analyst", "Business Intelligence Analyst"], ["full-time"], ["United Kingdom"], "remote",
            "Growth Hacker / Technical Rock Star", "VaporTech UK",
            "Are you a ninja who eats data for breakfast? We need a Growth Hacker to look at customer churn, build Excel and Tableau reports, and write basic Python scripts to automate metric pulls. Degree required.",
            "full-time", "London, UK / Remote", "United Kingdom", True,
            "ELIGIBLE", 2, "MID", False, "Buzzword-heavy marketing title is actually a data analyst position."
        ),
        (
            "indep_ambig_02", "ambiguous_descriptions", "Ravi Verma", "Frontend React Developer",
            ["React", "TypeScript", "HTML5", "CSS3", "JavaScript"],
            [{"role": "Frontend Engineer", "company": "WebSparks", "years": 3.0, "bullets": ["Engineered consumer-facing web apps in React and TypeScript."]}],
            [{"degree": "B.S. in Information Systems", "institution": "Symbiosis Pune"}],
            ["Frontend Engineer"], ["full-time"], ["India"], "remote",
            "Full Stack Web Architect", "Legacy Digital Marketing",
            "Urgent opening for a Full Stack Web Architect. The candidate must maintain our WordPress installations, install PHP plugins, and edit CSS styles. Experience with web design required.",
            "full-time", "Mumbai, India", "India", True,
            "ELIGIBLE", 0, "LOW", False, "Title says Full Stack Architect, but actual job is low-level WordPress/PHP maintenance."
        ),
        (
            "indep_ambig_03", "ambiguous_descriptions", "Grace Hopper Jr.", "Senior Distributed Systems Engineer",
            ["Go", "Kubernetes", "gRPC", "Docker", "PostgreSQL", "C++", "Linux"],
            [{"role": "Principal Systems Engineer", "company": "NetCore", "years": 7.0, "bullets": ["Engineered multi-tenant Kubernetes storage engines in Go and C++."]}],
            [{"degree": "Ph.D. in Computer Science", "institution": "MIT"}],
            ["Principal Engineer", "Distinguished Engineer", "Systems Architect"], ["full-time"], ["United States"], "remote",
            "Member of Technical Staff", "OpenAI Foundation",
            "OpenAI is seeking Members of Technical Staff to build high-scale distributed training infrastructure. Must possess deep experience in systems programming (Go, C++, or Rust), Kubernetes, Docker, and Linux. Advanced degree in CS required.",
            "full-time", "San Francisco, CA / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Understated title 'Member of Technical Staff' is an elite systems engineering role matching candidate."
        ),
        (
            "indep_ambig_04", "ambiguous_descriptions", "Maya Lin", "Enterprise Solution Architect",
            ["Enterprise Architecture", "Java", "Cloud", "AWS", "TOGAF", "Microservices", "REST"],
            [{"role": "Enterprise Architect", "company": "Global Financial Corp", "years": 8.0, "bullets": ["Designed strategic multi-year cloud modernization roadmaps across 12 product lines."]}],
            [{"degree": "M.S. in Computer Science", "institution": "University of Illinois"}],
            ["Enterprise Architect", "Solution Architect"], ["full-time"], ["United States"], "hybrid",
            "Software Architect", "HealthPlan America",
            "We are seeking a Software Architect to align enterprise systems with AWS cloud standards. Minimum 7+ years in enterprise architecture, strong background in Java or cloud systems, TOGAF or equivalent experience. Master's preferred.",
            "full-time", "Chicago, IL", "United States", False,
            "ELIGIBLE", 3, "HIGH", False, "Generic title matches deep enterprise architectural qualifications."
        ),
        (
            "indep_ambig_05", "ambiguous_descriptions", "Jordan Bell", "Senior React Native Mobile Engineer",
            ["React Native", "TypeScript", "JavaScript", "iOS", "Android", "Redux", "REST"],
            [{"role": "Mobile Developer", "company": "Appify", "years": 4.0, "bullets": ["Built cross-platform mobile apps for iOS and Android in React Native and TypeScript."]}],
            [{"degree": "B.S. in Computer Science", "institution": "UC San Diego"}],
            ["React Native Developer", "Mobile Engineer"], ["full-time"], ["United States"], "remote",
            "Software Engineer - Digital Experience", "Nordstrom",
            "Nordstrom is hiring a Software Engineer for Digital Experience to build customer mobile apps in React Native and TypeScript for iOS and Android devices. 3+ years mobile experience and CS degree required.",
            "full-time", "Seattle, WA / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Corporate 'Digital Experience' title is a 100% direct React Native mobile role."
        ),
        (
            "indep_ambig_06", "ambiguous_descriptions", "Kavita Reddy", "Data Scientist",
            ["Python", "Machine Learning", "PyTorch", "SQL", "Statistics", "Pandas"],
            [{"role": "Data Scientist", "company": "InsightIQ", "years": 3.0, "bullets": ["Trained supervised ML models for customer propensity using Python and PyTorch."]}],
            [{"degree": "M.S. in Data Science", "institution": "Columbia University"}],
            ["Data Scientist", "ML Engineer"], ["full-time"], ["United States"], "remote",
            "Product Operations Specialist", "SaaS Scale",
            "Product Operations Specialist needed. Must handle customer support tickets, manually verify billing discrepancies in Stripe, and respond to live chat inquiries. No coding required.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Technical title disguises a customer service support job. Low fit."
        ),
        (
            "indep_ambig_07", "ambiguous_descriptions", "Felix Baum", "DevOps & Cloud Engineer",
            ["Kubernetes", "AWS", "Terraform", "Docker", "CI/CD", "Linux"],
            [{"role": "Cloud Engineer", "company": "InfraTech", "years": 4.0, "bullets": ["Automated AWS deployments with Terraform and managed Kubernetes clusters."]}],
            [{"degree": "B.S. in CS", "institution": "RWTH Aachen"}],
            ["DevOps Engineer", "Cloud Engineer"], ["full-time"], ["Germany"], "remote",
            "Production Engineer", "Meta Platforms",
            "Meta is hiring Production Engineers. You will bridge software engineering and systems engineering, managing massive Linux container infrastructure, Kubernetes workloads, and CI/CD pipelines. 3+ years experience and CS degree required.",
            "full-time", "Frankfurt, Germany / Remote", "Germany", True,
            "ELIGIBLE", 3, "HIGH", False, "Meta's 'Production Engineer' title corresponds to Senior SRE/DevOps."
        ),
        (
            "indep_ambig_08", "ambiguous_descriptions", "Alicia Torres", "Backend Ruby on Rails Developer",
            ["Ruby", "Ruby on Rails", "PostgreSQL", "Redis", "RSpec", "Sidekiq", "Git"],
            [{"role": "Senior Ruby Developer", "company": "ShopStream", "years": 5.0, "bullets": ["Built e-commerce backend APIs in Ruby on Rails and PostgreSQL."]}],
            [{"degree": "B.S. in Computer Science", "institution": "University of Buenos Aires"}],
            ["Ruby on Rails Engineer", "Backend Developer"], ["full-time"], ["Argentina", "United States"], "remote",
            "Application Engineer", "GitHub",
            "GitHub is looking for an Application Engineer to scale our core web application. We are a massive Ruby on Rails platform using PostgreSQL, Redis, and background jobs. 4+ years Ruby on Rails experience and CS degree required.",
            "full-time", "Remote - Americas", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Generic 'Application Engineer' title at GitHub is a pure Ruby on Rails role."
        ),
        (
            "indep_ambig_09", "ambiguous_descriptions", "Daniel Craig", "Cyber Threat Intelligence Analyst",
            ["Threat Intelligence", "Python", "OSINT", "Malware Analysis", "SIEM", "Security"],
            [{"role": "Threat Analyst", "company": "CyberWatch", "years": 4.0, "bullets": ["Tracked state-sponsored threat actors and analyzed telemetry in SIEM."]}],
            [{"degree": "B.S. in Intelligence Studies", "institution": "Georgetown"}],
            ["Threat Intelligence Analyst", "Security Analyst"], ["full-time"], ["United States"], "remote",
            "Cyber Risk Consultant", "Deloitte Advisory",
            "Deloitte is seeking a Cyber Risk Consultant to deliver threat intelligence, malware advisory, and SIEM monitoring for Fortune 500 clients. 3+ years threat analysis experience and security clearance eligibility required.",
            "full-time", "Washington, DC / Remote", "United States", True,
            "ELIGIBLE", 2, "MID", False, "Consultancy title matches hands-on threat intelligence practitioner."
        ),
        (
            "indep_ambig_10", "ambiguous_descriptions", "Priya Nair", "Front-of-the-Frontend CSS & UI Specialist",
            ["HTML5", "CSS3", "Sass", "JavaScript", "Responsive Design", "Accessibility", "Figma"],
            [{"role": "UI Developer", "company": "DesignFirst", "years": 4.0, "bullets": ["Crafted accessible WCAG AA compliant UI components in HTML and Sass."]}],
            [{"degree": "B.A. in Graphic Design", "institution": "NID Ahmedabad"}],
            ["UI Developer", "Design Technologist"], ["full-time"], ["India"], "remote",
            "Frontend Systems Architect", "Quant Algorithmics",
            "Seeking a Frontend Systems Architect to design low-latency WebAssembly order execution trading terminals using C++ and WebSockets. Deep algorithmic multithreading required.",
            "full-time", "Mumbai, India", "India", True,
            "ELIGIBLE", 0, "LOW", False, "Design-focused UI developer is a total mismatch for low-latency C++/Wasm trading terminal."
        ),
    ]

    for c in ambiguous_cases:
        pairs.append(create_pair(*c))

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 4: INCOMPLETE PROFILES & EARLY CAREER (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    incomplete_cases = [
        (
            "indep_incomp_01", "incomplete_profiles", "Alex Chen", "CS Student seeking Summer Internship",
            ["Python", "Git", "SQL"],
            [],  # No professional experience listed
            [{"degree": "Candidate for B.S. in Computer Science (Junior)", "institution": "UC Berkeley"}],
            ["Software Engineer Intern", "Backend Intern"], ["internship"], ["United States"], "remote",
            "Software Engineering Summer Intern (2027)", "Palantir Technologies",
            "Palantir is seeking passionate students for our 2027 Summer Internship. Must be currently enrolled in an undergraduate degree in Computer Science. Basic knowledge of Python and Git required. No prior professional experience required.",
            "internship", "Palo Alto, CA / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Student with zero experience applying to appropriate college internship."
        ),
        (
            "indep_incomp_02", "incomplete_profiles", "Sam Taylor", "Self-Taught Junior Web Developer",
            ["JavaScript", "HTML5", "CSS3"],
            [],  # Incomplete profile - no experience, no degree
            [],
            ["Junior Web Developer"], ["full-time"], ["United States"], "remote",
            "Principal Distributed Systems Architect", "AWS Redshift",
            "AWS Redshift is looking for a Principal Architect. Requires 10+ years experience building distributed database query planners in C++ or Rust, Master's or PhD degree, and published distributed systems research.",
            "full-time", "Seattle, WA / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Incomplete junior profile applying to Principal Architect role. Strict mismatch."
        ),
        (
            "indep_incomp_03", "incomplete_profiles", "Jordan Lee", "Early Career Developer",
            ["Python", "FastAPI"],
            [{"role": "Junior Developer", "company": "Local Shop", "years": 0.8, "bullets": ["Assisted with Python backend bugfixes."]}],
            [{"degree": "B.A. in History", "institution": "State College"}],
            ["Junior Developer", "Software Engineer"], ["full-time"], ["United States"], "remote",
            "Staff Software Engineer (10+ YOE)", "Snowflake",
            "Snowflake requires a Staff Engineer with at least 8+ years experience in distributed systems, C++, and database internals. Bachelor's in CS required.",
            "full-time", "San Mateo, CA", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Severe experience and technical gap (0.8 YOE vs 8+ YOE required)."
        ),
        (
            "indep_incomp_04", "incomplete_profiles", "Chloe Martin", "Frontend Intern",
            ["React", "JavaScript", "CSS3"],
            [{"role": "Frontend Intern", "company": "Campus Tech", "years": 0.5, "bullets": ["Built responsive UI components."]}],
            [{"degree": "B.S. in Computer Science (in progress)", "institution": "McGill"}],
            ["Frontend Intern", "Junior Frontend Developer"], ["internship", "full-time"], ["Canada"], "remote",
            "Frontend Engineer Intern", "Shopify",
            "Shopify is hiring Frontend Interns. Must know React, JavaScript, and HTML/CSS. Open to current students and recent bootcamp grads. Bachelor's in progress accepted.",
            "internship", "Ottawa, Canada / Remote", "Canada", True,
            "ELIGIBLE", 3, "HIGH", False, "Intern with 6 months internship experience aligns with Shopify intern role."
        ),
        (
            "indep_incomp_05", "incomplete_profiles", "David Kim", "Incomplete Profile (Skills Only)",
            ["Python", "Django", "PostgreSQL", "Docker"],
            [],  # Candidate uploaded skills but forgot experience & education
            [],
            ["Python Developer"], ["full-time"], ["United States"], "remote",
            "Python Backend Developer", "Acme Health",
            "Looking for a Python Backend Developer with Django and PostgreSQL experience. Degree in Computer Science preferred but experience valued.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 1, "MID", False, "Skills match but missing experience and education history."
        ),
        (
            "indep_incomp_06", "incomplete_profiles", "Fatima Zahra", "Recent Graduate",
            ["Python", "Java", "SQL", "Git", "Algorithms"],
            [{"role": "Teaching Assistant", "company": "University CS Dept", "years": 1.0, "bullets": ["Graded algorithm assignments and led Python lab sessions."]}],
            [{"degree": "B.S. in Computer Science", "institution": "Al Akhawayn University"}],
            ["Junior Software Engineer", "Graduate Software Engineer"], ["full-time"], ["Morocco", "France"], "remote",
            "Graduate Software Development Program (2026)", "Societe Generale",
            "We are welcoming new graduates into our European software engineering cohort. Requirements: Recent Bachelor's degree in Computer Science, knowledge of Python or Java, and sound grasp of algorithms and SQL.",
            "full-time", "Paris, France / Remote", "France", True,
            "ELIGIBLE", 3, "HIGH", False, "Recent graduate with academic/TA background matches graduate program."
        ),
        (
            "indep_incomp_07", "incomplete_profiles", "Tyler Wright", "Self-Taught Fullstack Builder",
            ["Next.js", "React", "TypeScript", "Tailwind CSS", "Supabase", "Git"],
            [{"role": "Freelance Web Developer", "company": "Self-Employed", "years": 1.0, "bullets": ["Shipped 3 client websites using Next.js and Supabase."]}],
            [],  # No college degree
            ["Full Stack Developer", "Junior Web Developer"], ["full-time"], ["United States"], "remote",
            "Junior Full Stack Engineer (Next.js)", "LaunchPass",
            "We are seeking a junior full stack developer who loves building products in Next.js, React, TypeScript, and Tailwind CSS. No degree required — show us your projects!",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "No-degree job posting fits self-taught candidate perfectly."
        ),
        (
            "indep_incomp_08", "incomplete_profiles", "Hassan Ali", "Student Researcher",
            ["Python", "PyTorch", "C++", "Mathematics"],
            [{"role": "Undergraduate Researcher", "company": "AI Lab", "years": 1.0, "bullets": ["Researched transformer attention pruning techniques."]}],
            [{"degree": "B.S. in Mathematics & CS (Senior)", "institution": "UCLA"}],
            ["AI Research Intern", "Machine Learning Intern"], ["internship"], ["United States"], "remote",
            "AI Research Scientist (PhD Required)", "Meta FAIR",
            "Meta Fundamental AI Research (FAIR) is hiring Research Scientists. Requirements: PhD in Computer Science or Machine Learning, first-author publications at NeurIPS/ICML/CVPR, and 5+ years research experience.",
            "full-time", "Menlo Park, CA", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Undergraduate researcher applying to senior PhD Research Scientist role."
        ),
        (
            "indep_incomp_09", "incomplete_profiles", "Zack Morris", "Junior Quality Assurance",
            ["Manual Testing", "Jira", "Test Cases"],
            [{"role": "QA Tester", "company": "GameStudio", "years": 1.0, "bullets": ["Executed manual regression test passes for mobile games."]}],
            [{"degree": "Associate Degree", "institution": "Community College"}],
            ["QA Tester"], ["full-time"], ["United States"], "remote",
            "Senior SDET (Software Development Engineer in Test)", "Netflix",
            "Netflix is looking for a Senior SDET. Must write production test automation in Java/Go, configure distributed testing on AWS, and architect chaos engineering suites. 6+ years experience required.",
            "full-time", "Los Gatos, CA", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Manual tester applying to top-tier Senior SDET role."
        ),
        (
            "indep_incomp_10", "incomplete_profiles", "Isabella Rossi", "Junior Backend Developer",
            ["Go", "Docker", "PostgreSQL", "Git"],
            [{"role": "Junior Backend Developer", "company": "Milan SaaS", "years": 1.2, "bullets": ["Maintained REST API endpoints in Go with PostgreSQL."]}],
            [{"degree": "B.S. in Computer Engineering", "institution": "Politecnico di Milano"}],
            ["Junior Go Developer", "Backend Software Engineer"], ["full-time"], ["Italy", "European Union"], "remote",
            "Junior Backend Developer (Go)", "Satispay",
            "We are looking for a Junior Backend Developer to join our core payments squad. You will write clean, well-tested Go code and collaborate on PostgreSQL databases. 1+ year Go experience and degree required.",
            "full-time", "Milan, Italy / Remote", "Italy", True,
            "ELIGIBLE", 3, "HIGH", False, "Direct junior alignment on Go, PostgreSQL, and experience level."
        ),
    ]

    for c in incomplete_cases:
        pairs.append(create_pair(*c))

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 5: NEGATIONS & NOT-REQUIRED GUARDS (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    negation_cases = [
        (
            "indep_neg_01", "negation_guards", "Brendan Eich-Fan", "Pure JavaScript & TypeScript Architect",
            ["JavaScript", "TypeScript", "Node.js", "React", "PostgreSQL"],
            [{"role": "Staff JS Engineer", "company": "WebTech", "years": 6.0, "bullets": ["Engineered high-scale browser and server runtimes in TypeScript."]}],
            [{"degree": "B.S. in Computer Science", "institution": "Stanford"}],
            ["Staff Software Engineer", "Full Stack Engineer"], ["full-time"], ["United States"], "remote",
            "Backend Systems Engineer (Rust Only - No JavaScript / Node)", "Oxide Computer",
            "We build bare-metal hardware virtualization. Our software is written strictly in Rust and C. We have no JavaScript, and no Node.js is required or used in our stack. Candidates without Rust or C systems background will not be considered.",
            "full-time", "Emeryville, CA / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Job explicitly negates candidate's core technologies ('no JavaScript, no Node.js')."
        ),
        (
            "indep_neg_02", "negation_guards", "Pavel Durov-Fan", "Python Backend Specialist",
            ["Python", "FastAPI", "PostgreSQL", "Docker", "Linux"],
            [{"role": "Senior Python Developer", "company": "PyStream", "years": 5.0, "bullets": ["Built Python microservices."]}],
            [{"degree": "B.S. in CS", "institution": "State University"}],
            ["Python Backend Developer"], ["full-time"], ["United States"], "remote",
            "Python Microservices Engineer (No Java / Strictly Python)", "Cisco Cloud",
            "We are a pure Python organization. We strictly avoid Java — no Java required or used. Must have 4+ years of Python, FastAPI, and PostgreSQL with Docker. Bachelor's degree required.",
            "full-time", "San Jose, CA / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Candidate has Python. The negated skill ('no Java') should not trigger a false positive match on Java."
        ),
        (
            "indep_neg_03", "negation_guards", "Arun Joshi", "On-Premises Linux Sysadmin",
            ["Linux", "Bash", "Networking", "PostgreSQL", "Hardware"],
            [{"role": "Systems Administrator", "company": "DataBunker", "years": 5.0, "bullets": ["Maintained air-gapped on-premise Linux mainframes."]}],
            [{"degree": "B.Sc. in IT", "institution": "Pune University"}],
            ["Linux Systems Administrator"], ["full-time"], ["India"], "on-site",
            "Air-Gapped Systems Engineer (No Cloud / No AWS)", "National Defense Lab",
            "Must maintain secure on-premise Linux clusters. Strictly no cloud or AWS used due to national air-gap regulations. 4+ years Linux systems administration, networking, and hardware maintenance required.",
            "full-time", "Pune, India", "India", False,
            "ELIGIBLE", 3, "HIGH", False, "Candidate is an on-premise specialist. Negation 'no cloud / no AWS' must be respected."
        ),
        (
            "indep_neg_04", "negation_guards", "Rebecca Stone", "Senior Java Engineer",
            ["Java", "Spring Boot", "Kafka", "PostgreSQL"],
            [{"role": "Senior Java Developer", "company": "FinanceFirst", "years": 6.0, "bullets": ["Built enterprise services in Java."]}],
            [{"degree": "B.S. in Computer Science", "institution": "Rutgers"}],
            ["Senior Java Developer"], ["full-time"], ["United States"], "remote",
            "Go Microservices Architect (Without Java)", "FinTech Modern",
            "We are decommissioning our legacy stack. This role is 100% Go. We operate strictly without Java, and Java is not required or permitted in new services. 4+ years Go experience required.",
            "full-time", "New York, NY / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Posting states 'without Java' — candidate only knows Java."
        ),
        (
            "indep_neg_05", "negation_guards", "Ken Thompson-Fan", "C Systems Developer",
            ["C", "Linux", "Algorithms", "Git"],
            [{"role": "C Developer", "company": "KernelWorks", "years": 4.0, "bullets": ["Wrote kernel drivers in C on Linux."]}],
            [{"degree": "B.S. in Computer Engineering", "institution": "Texas A&M"}],
            ["Systems Software Engineer"], ["full-time"], ["United States"], "remote",
            "Modern C Systems Engineer (No C++ / Pure C Only)", "Embedded Realtime",
            "We develop safety-critical aerospace microcontrollers in pure ANSI C. Absolutely no C++ is allowed in our flight systems. 3+ years pure C programming on Linux required.",
            "full-time", "Houston, TX / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Candidate has pure C. Negation 'no C++' correctly keeps score high without triggering C++ requirement."
        ),
        (
            "indep_neg_06", "negation_guards", "Simon Pegg", "PHP Fullstack Developer",
            ["PHP", "Laravel", "MySQL", "JavaScript"],
            [{"role": "PHP Developer", "company": "WebShop", "years": 4.0, "bullets": ["Built PHP sites."]}],
            [{"degree": "B.S. in Computing", "institution": "Bristol"}],
            ["PHP Developer"], ["full-time"], ["United Kingdom"], "remote",
            "Enterprise Java Engineer (PHP Skills Not Accepted)", "London Clearing House",
            "We require a Java and Spring Boot engineer for high-frequency trading. Web scripting languages like PHP or Ruby are strictly not accepted. Minimum 4 years core Java required.",
            "full-time", "London, UK", "United Kingdom", False,
            "ELIGIBLE", 0, "LOW", False, "Posting strictly rejects candidate's skill set ('PHP skills not accepted')."
        ),
        (
            "indep_neg_07", "negation_guards", "Linus Torvalds-Fan", "Open Source Linux Kernel Hacker",
            ["C", "Linux", "Git", "Bash"],
            [{"role": "Kernel Contributor", "company": "OS Foundation", "years": 5.0, "bullets": ["Maintained Linux kernel subsystems."]}],
            [{"degree": "B.S. in CS", "institution": "Helsinki"}],
            ["Linux Systems Engineer"], ["full-time"], ["European Union"], "remote",
            "Linux Systems Architect (No Windows / Strictly Non-Microsoft)", "Suse Linux",
            "Join our core OS team. Strictly no Windows experience required or wanted. 4+ years Linux internals, C programming, and Git required. Degree in CS required.",
            "full-time", "Nuremberg, Germany / Remote", "Germany", True,
            "ELIGIBLE", 3, "HIGH", False, "Negation 'no Windows' accurately ignored."
        ),
        (
            "indep_neg_08", "negation_guards", "Tara MacLeod", "NoSQL Specialist (MongoDB)",
            ["MongoDB", "Express", "Node.js", "JavaScript"],
            [{"role": "NoSQL Developer", "company": "DocumentCloud", "years": 4.0, "bullets": ["Managed MongoDB replica sets."]}],
            [{"degree": "B.S. in IT", "institution": "Glasgow"}],
            ["Database Developer"], ["full-time"], ["United Kingdom"], "remote",
            "Relational Database Architect (No Document Stores / No MongoDB)", "Edinburgh Banking",
            "Our audit compliance mandates strict ACID relational guarantees. We operate strictly with PostgreSQL; document databases such as MongoDB are prohibited. 4+ years relational SQL experience required.",
            "full-time", "Edinburgh, UK", "United Kingdom", False,
            "ELIGIBLE", 0, "LOW", False, "Candidate's core database is expressly prohibited by the job."
        ),
        (
            "indep_neg_09", "negation_guards", "Wei Zhang", "Front-end Mobile Developer",
            ["Flutter", "Dart", "iOS", "Android"],
            [{"role": "Flutter Developer", "company": "AppFlow", "years": 3.0, "bullets": ["Built cross-platform apps in Flutter."]}],
            [{"degree": "B.Eng in Software", "institution": "Tsinghua"}],
            ["Flutter Developer", "Mobile Engineer"], ["full-time"], ["Singapore"], "remote",
            "Flutter Mobile Engineer (No React Native Needed)", "Grab Singapore",
            "Grab is hiring a Flutter Mobile Developer. No React Native knowledge is needed or expected. Required: 3+ years Flutter/Dart development, published apps on iOS and Android. Degree required.",
            "full-time", "Singapore / Remote", "Singapore", True,
            "ELIGIBLE", 3, "HIGH", False, "Negation 'no React Native needed' does not penalize Flutter candidate."
        ),
        (
            "indep_neg_10", "negation_guards", "Rachel Green", "Corporate Recruiter",
            ["Talent Acquisition", "Sourcing", "HR", "Interviews"],
            [{"role": "Senior Recruiter", "company": "PeopleCorp", "years": 5.0, "bullets": ["Hired 150+ engineers annually."]}],
            [{"degree": "B.A. in Psychology", "institution": "NYU"}],
            ["Technical Recruiter", "Talent Acquisition Partner"], ["full-time"], ["United States"], "remote",
            "Lead Software Engineer (No Recruiters Please)", "Stripe",
            "We are looking for a Lead Backend Engineer to build payment infrastructure in Ruby and Go. Direct applicants only — no agencies or recruiters will be accepted.",
            "full-time", "San Francisco, CA / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Candidate matches the negated keyword 'recruiters', but the job is an engineering role."
        ),
    ]

    for c in negation_cases:
        pairs.append(create_pair(*c))

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 6: MANDATORY HARD REQUIREMENTS & DISQUALIFIERS (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    mandatory_cases = [
        (
            "indep_mand_01", "mandatory_hard_requirements", "Bob Smith", "Mid-level Full Stack Developer",
            ["Python", "FastAPI", "React", "PostgreSQL"],
            [{"role": "Software Developer", "company": "WebTech", "years": 3.0, "bullets": ["Built web features."]}],
            [{"degree": "B.S. in Computer Science", "institution": "State University"}],
            ["Full Stack Developer"], ["full-time"], ["United States"], "remote",
            "Principal Cryptography Researcher (Ph.D. Required)", "National Cyber Research",
            "Mandatory requirement: Ph.D. in Mathematics or Cryptography required. Candidates with only a Bachelor's degree will be disqualified. Must have published post-quantum cryptography research.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Disqualified by hard degree requirement (Ph.D. required vs B.S.)."
        ),
        (
            "indep_mand_02", "mandatory_hard_requirements", "Alice Johnson", "Senior Security Engineer",
            ["Python", "Security", "AppSec", "Linux", "Docker"],
            [{"role": "Senior AppSec Engineer", "company": "CyberSecure", "years": 5.0, "bullets": ["Secured cloud applications."]}],
            [{"degree": "B.S. in Cybersecurity", "institution": "George Mason"}],
            ["Security Engineer"], ["full-time"], ["United States"], "on-site",
            "Lead Defense Systems Engineer (Active TS/SCI Clearance Mandatory)", "Lockheed Martin",
            "Mandatory requirement: Active Top Secret / SCI security clearance is strictly required on day one. Candidates without an active US clearance cannot be processed.",
            "full-time", "Reston, VA", "United States", False,
            "ELIGIBLE", 1, "MID", False, "High technical alignment but missing mandatory security clearance."
        ),
        (
            "indep_mand_03", "mandatory_hard_requirements", "Chris Evans", "Junior Cloud Associate",
            ["AWS", "Linux", "Docker"],
            [{"role": "Cloud Support Tech", "company": "ManagedServices", "years": 1.5, "bullets": ["Provided ticket resolution for AWS instances."]}],
            [{"degree": "B.S. in IT", "institution": "Florida State"}],
            ["Cloud Engineer"], ["full-time"], ["United States"], "remote",
            "Staff Cloud Architect (10+ Years Experience Strictly Required)", "Databricks",
            "Mandatory requirement: Minimum of 10+ years of production cloud architecture experience is non-negotiable. Please do not apply if you have under 10 years experience.",
            "full-time", "San Francisco, CA / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Candidate has 1.5 YOE against mandatory 10+ YOE."
        ),
        (
            "indep_mand_04", "mandatory_hard_requirements", "Dr. Emily Watson", "Senior Data Scientist & Bioinformatician",
            ["Python", "R", "Machine Learning", "Bioinformatics", "Statistics", "SQL"],
            [{"role": "Senior Bioinformatician", "company": "Genomics Lab", "years": 6.0, "bullets": ["Analyzed genomic sequencings using Python, R, and statistical models."]}],
            [{"degree": "Ph.D. in Computational Biology", "institution": "Johns Hopkins"}],
            ["Senior Data Scientist", "Bioinformatics Scientist"], ["full-time"], ["United States"], "remote",
            "Lead Computational Biologist (Ph.D. Required)", "Illumina Genomics",
            "Illumina is seeking a Lead Computational Biologist. Requirements: Ph.D. in Computational Biology or Bioinformatics is required. 5+ years experience in genomic modeling, Python, and R required.",
            "full-time", "San Diego, CA / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Candidate strictly satisfies the hard Ph.D. and specialized domain requirement."
        ),
        (
            "indep_mand_05", "mandatory_hard_requirements", "Jake Sully", "Junior Python Developer",
            ["Python", "Flask", "SQL"],
            [{"role": "Junior Developer", "company": "StartApp", "years": 1.0, "bullets": ["Wrote Flask endpoints."]}],
            [],  # No degree
            ["Python Developer"], ["full-time"], ["United States"], "remote",
            "Senior Regulatory Compliance Software Engineer (Degree Mandatory)", "FINRA",
            "Mandatory requirement: Accredited Bachelor's degree in Computer Science is strictly required by regulatory bylaws. 5+ years financial compliance engineering experience required.",
            "full-time", "Washington, DC / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Candidate lacks mandatory degree and experience."
        ),
        (
            "indep_mand_06", "mandatory_hard_requirements", "Sunita Rao", "Certified Kubernetes Administrator (CKA)",
            ["Kubernetes", "Docker", "Linux", "Terraform", "CI/CD"],
            [{"role": "Kubernetes Administrator", "company": "CloudPulse", "years": 4.0, "bullets": ["Administered bare-metal Kubernetes fleets holding official CKA certification."]}],
            [{"degree": "B.Tech in CS", "institution": "VTU Belgaum"}],
            ["Kubernetes Engineer", "Platform SRE"], ["full-time"], ["India", "United States"], "remote",
            "Kubernetes Infrastructure Engineer (CKA Certification Required)", "Red Hat",
            "Mandatory requirement: Active Certified Kubernetes Administrator (CKA) credential required. 3+ years managing production Kubernetes, Docker, and Linux. Bachelor's in CS required.",
            "full-time", "Remote - Worldwide", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Candidate holds mandatory CKA certification and meets all criteria."
        ),
        (
            "indep_mand_07", "mandatory_hard_requirements", "George Lucas", "Frontend Developer",
            ["React", "JavaScript", "HTML5", "CSS3"],
            [{"role": "Frontend Developer", "company": "WebShop", "years": 2.0, "bullets": ["Built React sites."]}],
            [{"degree": "B.A. in English", "institution": "USC"}],
            ["Frontend Developer"], ["full-time"], ["United States"], "remote",
            "Senior Embedded Flight Software Engineer (FAA Safety Clearance)", "Boeing Aerospace",
            "Mandatory: FAA DO-178C avionics certification experience and C/Ada programming mandatory. Active DOD Secret clearance required.",
            "full-time", "Seattle, WA", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Complete domain and mandatory credential mismatch."
        ),
        (
            "indep_mand_08", "mandatory_hard_requirements", "Diana Prince", "Security Analyst",
            ["Security", "CISSP", "Audit", "OWASP", "Linux"],
            [{"role": "Lead Security Auditor", "company": "ShieldCorp", "years": 5.0, "bullets": ["Conducted ISO 27001 and SOC 2 audits with active CISSP certification."]}],
            [{"degree": "B.S. in Information Security", "institution": "Penn State"}],
            ["Security Auditor", "Information Security Officer"], ["full-time"], ["United States"], "remote",
            "Senior Information Security Auditor (CISSP Required)", "PwC Advisory",
            "PwC is seeking a Senior Security Auditor. Mandatory requirement: Current CISSP certification is required. 4+ years security audit experience and Bachelor's degree required.",
            "full-time", "New York, NY / Remote", "United States", True,
            "ELIGIBLE", 3, "HIGH", False, "Meets mandatory certification and professional domain criteria."
        ),
        (
            "indep_mand_09", "mandatory_hard_requirements", "Ethan Hunt", "Network Technician",
            ["Cisco", "Routing", "Hardware", "Linux"],
            [{"role": "Network Tech", "company": "NetWire", "years": 2.0, "bullets": ["Ran network cables and configured switches."]}],
            [{"degree": "Associate Degree", "institution": "Northern Virginia CC"}],
            ["Network Engineer"], ["full-time"], ["United States"], "on-site",
            "Senior Director of Engineering (15+ Years YOE Mandatory)", "Google Cloud",
            "Mandatory requirement: Minimum 15+ years engineering leadership experience managing organizations of 100+ engineers. Advanced CS degree required.",
            "full-time", "Sunnyvale, CA", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Junior technician applying to Executive Director role."
        ),
        (
            "indep_mand_10", "mandatory_hard_requirements", "Maya Angelou-Fan", "Copywriter",
            ["Content Writing", "Copywriting", "SEO", "Editing"],
            [{"role": "Senior Copywriter", "company": "AdAgency", "years": 5.0, "bullets": ["Wrote marketing copy."]}],
            [{"degree": "B.A. in Journalism", "institution": "Northwestern"}],
            ["Senior Copywriter"], ["full-time"], ["United States"], "remote",
            "Senior Quant Developer (PhD in Financial Mathematics Mandatory)", "Two Sigma",
            "Mandatory requirement: Ph.D. in Financial Mathematics, Physics, or Computer Science strictly required. Mastery of C++ and stochastic calculus required.",
            "full-time", "New York, NY", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Copywriter applying to Quant PhD position."
        ),
    ]

    for c in mandatory_cases:
        pairs.append(create_pair(*c))

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 7: LOCATION & VISA CONFLICTS (HIGH TECHNICAL FIT BUT INELIGIBLE) (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    # INVARIANT: Technical relevance grade reflects technical skill alignment (3 = High),
    # while expected_eligibility is strictly INELIGIBLE.
    location_cases = [
        (
            "indep_loc_01", "location_visa_conflict", "Rohit Deshmukh", "Senior Python & Machine Learning Engineer",
            ["Python", "PyTorch", "FastAPI", "Docker", "PostgreSQL", "Kubernetes", "LangChain"],
            [{"role": "Senior AI Developer", "company": "ScaleAI India", "years": 5.0, "bullets": ["Built Python microservices and PyTorch RAG pipelines."]}],
            [{"degree": "B.Tech in Computer Science", "institution": "IIT Madras"}],
            ["Senior Python Engineer", "Applied AI Engineer"], ["full-time"], ["India"], "remote",  # Candidate only authorized in India
            "Senior AI Engineer (US Citizens Only - Onsite Pentagon)", "US Defense Digital Service",
            "Mandatory requirement: Due to federal defense regulations, this role is open strictly to United States Citizens residing in the US. No international applicants or visa sponsorship allowed. Technical stack: Python, PyTorch, FastAPI, and Kubernetes. 4+ years experience required.",
            "full-time", "Washington, DC", "United States", False,
            "INELIGIBLE", 3, "HIGH", True, "High technical fit (85+), but candidate country is India and job strictly requires US citizenship. Must be INELIGIBLE."
        ),
        (
            "indep_loc_02", "location_visa_conflict", "John Doe", "Senior Go Backend Architect",
            ["Golang", "Kubernetes", "Docker", "gRPC", "PostgreSQL", "Microservices"],
            [{"role": "Staff Go Engineer", "company": "CloudFin", "years": 6.0, "bullets": ["Architected distributed Go microservices with gRPC."]}],
            [{"degree": "B.S. in Computer Science", "institution": "Austin University"}],
            ["Senior Go Engineer"], ["full-time"], ["United States"], "remote",  # Candidate only in US
            "Lead Go Engineer (Australia PR / Citizen Only - No Sponsorship)", "Canva Sydney",
            "Candidates must have existing right to work in Australia (Australian Citizen or Permanent Resident). We cannot provide visa sponsorship or hire remotely outside Australia. Required: 5+ years Go, Kubernetes, and gRPC.",
            "full-time", "Sydney, Australia", "Australia", False,
            "INELIGIBLE", 3, "HIGH", True, "Technically a 90%+ match on Go/K8s, but located in US applying to Australia PR-only position."
        ),
        (
            "indep_loc_03", "location_visa_conflict", "Pierre Martin", "Senior React & TypeScript Developer",
            ["React", "TypeScript", "Next.js", "Tailwind CSS", "GraphQL"],
            [{"role": "Senior Frontend Engineer", "company": "ParisApp", "years": 5.0, "bullets": ["Engineered responsive React web apps in TypeScript."]}],
            [{"degree": "Master in Software", "institution": "Telecom Paris"}],
            ["Senior Frontend Engineer"], ["full-time"], ["France"], "remote",  # Candidate only in France
            "Senior React Engineer (UK Right to Work Required - No Visa)", "Monzo Bank London",
            "Must possess unrestricted right to work in the United Kingdom. We are unable to sponsor visas or hire contractors outside the UK. 4+ years React, TypeScript, and Next.js required.",
            "full-time", "London, UK", "United Kingdom", False,
            "INELIGIBLE", 3, "HIGH", True, "Candidate is in France with no UK right to work."
        ),
        (
            "indep_loc_04", "location_visa_conflict", "Fatima Al-Nuaimi", "Senior Cloud Infrastructure Engineer",
            ["AWS", "Terraform", "Kubernetes", "Docker", "Linux", "CI/CD"],
            [{"role": "Lead Cloud Architect", "company": "Gulf Cloud", "years": 6.0, "bullets": ["Automated multi-region AWS cloud with Terraform."]}],
            [{"degree": "B.S. in Computer Engineering", "institution": "UAE University"}],
            ["Cloud Architect"], ["full-time"], ["United Arab Emirates"], "remote",  # UAE only
            "Senior Cloud Engineer (EU Citizens Only - Strict GDPR Data Sovereignty)", "SAP Germany",
            "Due to EU data residency mandates, this position requires an EU passport holder residing in Germany or France. Remote work outside the European Economic Area is strictly prohibited. Required: 5+ years AWS, Terraform, and Kubernetes.",
            "full-time", "Walldorf, Germany", "Germany", False,
            "INELIGIBLE", 3, "HIGH", True, "High technical skills, but barred by EU data residency and residency constraints."
        ),
        (
            "indep_loc_05", "location_visa_conflict", "Kenji Sato", "Senior iOS Developer",
            ["Swift", "iOS", "SwiftUI", "Combine", "CoreData"],
            [{"role": "Lead iOS Developer", "company": "Tokyo Mobile", "years": 5.0, "bullets": ["Built consumer iOS applications with Swift."]}],
            [{"degree": "B.Eng in Computer Science", "institution": "Tokyo Tech"}],
            ["Senior iOS Engineer"], ["full-time"], ["Japan"], "remote",  # Japan only
            "Senior iOS Engineer (Must reside in Canada - Canadian PR/Citizen)", "Wealthsimple",
            "This role is strictly open to Canadian Citizens and Permanent Residents currently residing in Canada. No offshore or overseas hiring permitted. 4+ years native iOS development with Swift and SwiftUI required.",
            "full-time", "Toronto, Canada", "Canada", False,
            "INELIGIBLE", 3, "HIGH", True, "Candidate is in Japan applying to Canada-only position."
        ),
        (
            "indep_loc_06", "location_visa_conflict", "Maria Santos", "Senior Java & Spring Boot Engineer",
            ["Java", "Spring Boot", "PostgreSQL", "Kafka", "Docker", "Microservices"],
            [{"role": "Senior Java Developer", "company": "Manila FinTech", "years": 5.0, "bullets": ["Built enterprise banking services in Java."]}],
            [{"degree": "B.S. in CS", "institution": "University of Philippines"}],
            ["Senior Java Developer"], ["full-time"], ["Philippines"], "remote",  # Philippines only
            "Senior Java Microservices Engineer (US Security Clearance Required)", "Northrop Grumman",
            "Position requires US Citizenship and eligibility for DoD Secret Clearance. Overseas applicants not eligible. 4+ years Java and Spring Boot experience required.",
            "full-time", "McLean, VA", "United States", False,
            "INELIGIBLE", 3, "HIGH", True, "Clearance and citizenship blocker despite strong Java experience."
        ),
        (
            "indep_loc_07", "location_visa_conflict", "Oliver Brown", "Senior DevOps Engineer",
            ["Terraform", "Kubernetes", "AWS", "Docker", "Linux"],
            [{"role": "Senior SRE", "company": "Sydney Cloud", "years": 5.0, "bullets": ["Managed Kubernetes on AWS."]}],
            [{"degree": "B.S. in Computing", "institution": "UNSW Sydney"}],
            ["DevOps Engineer"], ["full-time"], ["Australia"], "remote",  # Australia only
            "Senior Platform Engineer (Must reside in Switzerland / Swiss Citizen)", "CERN Switzerland",
            "Candidates must be Swiss nationals or EU citizens residing in Switzerland. Remote work from outside Switzerland is not supported. Required: 4+ years Kubernetes, Terraform, and Linux.",
            "full-time", "Geneva, Switzerland", "Switzerland", False,
            "INELIGIBLE", 3, "HIGH", True, "Australia resident applying to Switzerland-only position."
        ),
        (
            "indep_loc_08", "location_visa_conflict", "Deepak Chopra", "Senior Data Engineer",
            ["Python", "SQL", "Apache Spark", "Snowflake", "dbt"],
            [{"role": "Lead Data Engineer", "company": "Delhi BigData", "years": 5.0, "bullets": ["Managed Snowflake and Spark pipelines."]}],
            [{"degree": "B.Tech in Information Technology", "institution": "Delhi Tech"}],
            ["Senior Data Engineer"], ["full-time"], ["India"], "remote",  # India only
            "Senior Data Platform Engineer (Strictly On-Site Singapore - Employment Pass Unavailable)", "DBS Bank",
            "This position requires physical daily on-site presence in Singapore. We are currently unable to sponsor new Employment Passes; local Singapore citizens or PR holders only. Required: 4+ years Python, SQL, Spark, and Snowflake.",
            "full-time", "Singapore", "Singapore", False,
            "INELIGIBLE", 3, "HIGH", True, "High data engineering fit, but physically restricted to local Singapore residents."
        ),
        (
            "indep_loc_09", "location_visa_conflict", "Beatriz Lima", "Senior Full Stack Engineer",
            ["TypeScript", "React", "Node.js", "PostgreSQL", "Docker"],
            [{"role": "Full Stack Lead", "company": "Rio Tech", "years": 5.0, "bullets": ["Built web applications in TypeScript and Node.js."]}],
            [{"degree": "B.S. in Computer Science", "institution": "UFRJ Brazil"}],
            ["Senior Full Stack Engineer"], ["full-time"], ["Brazil"], "remote",  # Brazil only
            "Staff Full Stack Developer (Irish Stamp 4 / EU Passport Required)", "AIB Bank Dublin",
            "Applicants must have existing legal right to work in Ireland without sponsorship (Stamp 4 or EU Passport). Required: 5+ years TypeScript, React, and Node.js.",
            "full-time", "Dublin, Ireland", "Ireland", False,
            "INELIGIBLE", 3, "HIGH", True, "Candidate in Brazil without EU/Irish right to work."
        ),
        (
            "indep_loc_10", "location_visa_conflict", "Dmitry Ivanov", "Senior C++ Systems Engineer",
            ["C++", "Linux", "Multithreading", "Algorithms", "Git"],
            [{"role": "Staff C++ Developer", "company": "CoreSys", "years": 6.0, "bullets": ["Engineered low-latency C++ engines."]}],
            [{"degree": "M.S. in Applied Mathematics", "institution": "Moscow State"}],
            ["Senior C++ Engineer"], ["full-time"], ["Kazakhstan"], "remote",  # Kazakhstan
            "C++ Autonomous Driving Systems Engineer (US Citizen / Green Card Required)", "Waymo",
            "Due to ITAR and US autonomous vehicle export regulations, applicants must be US Persons (US Citizen or Permanent Resident). 5+ years C++ multithreading on Linux required.",
            "full-time", "Mountain View, CA", "United States", False,
            "INELIGIBLE", 3, "HIGH", True, "ITAR export controls block non-US person despite 90%+ C++ technical fit."
        ),
    ]

    for c in location_cases:
        pairs.append(create_pair(*c))

    # ─────────────────────────────────────────────────────────────────────────────
    # CATEGORY 8: CROSS-DOMAIN MISMATCHES & LOW FIT (10 PAIRS)
    # ─────────────────────────────────────────────────────────────────────────────
    mismatch_cases = [
        (
            "indep_low_01", "cross_domain_mismatch", "Sarah Jenkins", "Graphic Designer & Illustrator",
            ["Photoshop", "Illustrator", "Figma", "Typography", "Branding"],
            [{"role": "Lead Graphic Designer", "company": "CreativeAgency", "years": 5.0, "bullets": ["Designed brand books and marketing assets in Photoshop and Illustrator."]}],
            [{"degree": "B.F.A. in Graphic Design", "institution": "RISD"}],
            ["Graphic Designer", "Visual Designer"], ["full-time"], ["United States"], "remote",
            "Senior Rust Database Kernel Engineer", "ScatteredDB",
            "We are seeking a Senior Systems Engineer to implement distributed consensus and LSM-tree storage engines in Rust and C. 5+ years systems programming, deep Linux kernel knowledge, and CS degree required.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Complete cross-domain mismatch (Graphic Designer vs Rust DB Kernel Engineer)."
        ),
        (
            "indep_low_02", "cross_domain_mismatch", "Tom Bradley", "Senior Corporate Accountant",
            ["Accounting", "QuickBooks", "Tax", "Excel", "GAAP", "Auditing"],
            [{"role": "Senior Accountant", "company": "AuditFirm", "years": 6.0, "bullets": ["Prepared corporate tax returns and GAAP financial statements."]}],
            [{"degree": "B.S. in Accounting", "institution": "Penn State"}],
            ["Corporate Accountant"], ["full-time"], ["United States"], "remote",
            "Senior Cloud Security Architect", "CrowdStrike",
            "Seeking a Senior Cloud Security Architect to design zero-trust networks on AWS and GCP. Deep knowledge of IAM, OAuth, SIEM, penetration testing, and Linux required. 5+ years security experience.",
            "full-time", "Austin, TX / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Accountant applying to Cloud Security Architect role."
        ),
        (
            "indep_low_03", "cross_domain_mismatch", "Emily Blunt-Fan", "Executive Assistant",
            ["Calendar Management", "Travel Coordination", "Microsoft Office", "Event Planning"],
            [{"role": "Executive Assistant", "company": "C-Suite Office", "years": 4.0, "bullets": ["Managed calendars and travel for 4 vice presidents."]}],
            [{"degree": "B.A. in Communications", "institution": "Boston University"}],
            ["Executive Assistant"], ["full-time"], ["United States"], "remote",
            "Staff Machine Learning Engineer (Large Language Models)", "DeepMind",
            "DeepMind is hiring a Staff ML Engineer. Requirements: PhD or MS in CS, 5+ years developing transformer architectures, PyTorch, CUDA kernel optimization, and distributed training.",
            "full-time", "New York, NY / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Executive Assistant applying to Staff Deep Learning / LLM Engineer role."
        ),
        (
            "indep_low_04", "cross_domain_mismatch", "Jack Ryan", "Warehouse Operations Supervisor",
            ["Logistics", "Inventory Management", "Supply Chain", "Forklift", "Safety"],
            [{"role": "Warehouse Supervisor", "company": "FreightLine", "years": 4.0, "bullets": ["Managed inventory distribution across 200k sq ft facility."]}],
            [{"degree": "High School Diploma", "institution": "Lincoln High"}],
            ["Logistics Supervisor"], ["full-time"], ["United States"], "on-site",
            "Lead Frontend Web Engineer (React & TypeScript)", "Stripe",
            "Stripe is hiring a Lead Frontend Engineer. Must possess 5+ years experience building complex web apps in React, TypeScript, Next.js, and modern CSS. Degree in CS required.",
            "full-time", "Seattle, WA / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Warehouse supervisor applying to Lead Frontend Engineer."
        ),
        (
            "indep_low_05", "cross_domain_mismatch", "Chloe Bennett", "Licensed Real Estate Agent",
            ["Real Estate", "Sales", "Contract Negotiation", "Client Relations"],
            [{"role": "Realtor", "company": "Keller Realty", "years": 5.0, "bullets": ["Brokered residential sales totaling $20M."]}],
            [{"degree": "B.A. in Business", "institution": "ASU"}],
            ["Real Estate Broker"], ["full-time"], ["United States"], "on-site",
            "DevOps / SRE Platform Engineer", "HashiCorp",
            "Seeking an experienced DevOps Engineer to maintain Terraform and Kubernetes infrastructure on AWS. 4+ years Linux systems and Docker experience required.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Real estate agent applying to DevOps engineer."
        ),
        (
            "indep_low_06", "cross_domain_mismatch", "Marcus Brody", "Elementary School Teacher",
            ["Curriculum Planning", "Classroom Management", "Child Education", "Parent Communication"],
            [{"role": "5th Grade Teacher", "company": "Oak Valley School", "years": 5.0, "bullets": ["Taught mathematics and reading to elementary cohorts."]}],
            [{"degree": "B.Ed. in Elementary Education", "institution": "Indiana University"}],
            ["Elementary Teacher"], ["full-time"], ["United States"], "on-site",
            "Senior Blockchain Protocol Engineer (Solidity & Rust)", "Uniswap Labs",
            "Uniswap Labs is hiring a Protocol Engineer to write smart contracts in Solidity and Rust. Deep knowledge of EVM internals, cryptography, and DeFi liquidity pools required.",
            "full-time", "New York, NY / Remote", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "School teacher applying to Blockchain Protocol Engineer."
        ),
        (
            "indep_low_07", "cross_domain_mismatch", "Chef Gordon", "Executive Chef",
            ["Culinary Arts", "Menu Design", "Kitchen Management", "Food Safety"],
            [{"role": "Executive Chef", "company": "Bistro Deluxe", "years": 7.0, "bullets": ["Managed fine dining kitchen brigade and menu curation."]}],
            [{"degree": "Associate in Culinary Arts", "institution": "CIA Hyde Park"}],
            ["Executive Chef"], ["full-time"], ["United States"], "on-site",
            "Senior Bioinformatician / Genomic Data Analyst", "Broad Institute",
            "We are seeking a Bioinformatician with 4+ years experience analyzing genomic sequencing pipelines using Python, R, and statistical genomics. Advanced degree required.",
            "full-time", "Cambridge, MA", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Chef applying to Bioinformatician."
        ),
        (
            "indep_low_08", "cross_domain_mismatch", "Tony Stark-Fan", "Welder & Metal Fabricator",
            ["MIG Welding", "TIG Welding", "Blueprint Reading", "Metal Fabrication"],
            [{"role": "Senior Welder", "company": "HeavyForge", "years": 6.0, "bullets": ["Fabricated structural steel components to precision blueprints."]}],
            [{"degree": "Vocational Certificate", "institution": "Welding Academy"}],
            ["Welder"], ["full-time"], ["United States"], "on-site",
            "Senior iOS Mobile Engineer (Swift & SwiftUI)", "Apple",
            "Apple is seeking an iOS Engineer to work on core iOS frameworks using Swift, SwiftUI, and Objective-C. 4+ years native iOS development required.",
            "full-time", "Cupertino, CA", "United States", False,
            "ELIGIBLE", 0, "LOW", False, "Welder applying to iOS engineer."
        ),
        (
            "indep_low_09", "cross_domain_mismatch", "Olivia Pope-Fan", "Public Relations Specialist",
            ["Crisis Communication", "Press Releases", "Media Relations", "Public Speaking"],
            [{"role": "PR Director", "company": "Apex Communications", "years": 5.0, "bullets": ["Directed crisis media responses and national press releases."]}],
            [{"degree": "B.A. in Public Relations", "institution": "George Washington"}],
            ["PR Specialist", "Media Strategist"], ["full-time"], ["United States"], "remote",
            "Lead Database Kernel Engineer (C & PostgreSQL Internals)", "Supabase",
            "Supabase is hiring a C engineer to extend PostgreSQL query planners, foreign data wrappers, and write C extensions. Deep C programming and relational engine internals required.",
            "full-time", "Remote - Global", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "PR Director applying to PostgreSQL C Kernel Engineer."
        ),
        (
            "indep_low_10", "cross_domain_mismatch", "Dr. Gregory House-Fan", "Clinical Physician",
            ["Diagnostic Medicine", "Patient Care", "Pharmacology", "Internal Medicine"],
            [{"role": "Attending Physician", "company": "Metro Health Hospital", "years": 8.0, "bullets": ["Diagnosed complex clinical cases in internal medicine."]}],
            [{"degree": "M.D. in Medicine", "institution": "Johns Hopkins Medical School"}],
            ["Physician"], ["full-time"], ["United States"], "on-site",
            "Senior Site Reliability Engineer (Kubernetes & AWS)", "Datadog",
            "Join our SRE team managing thousands of Kubernetes nodes on AWS using Terraform, Prometheus, and Golang. 4+ years cloud infrastructure SRE required.",
            "full-time", "Remote - US", "United States", True,
            "ELIGIBLE", 0, "LOW", False, "Medical doctor applying to SRE / Kubernetes engineer."
        ),
    ]

    for c in mismatch_cases:
        pairs.append(create_pair(*c))

    return pairs

if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent.parent / "data" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "independent_eval_dataset.json"

    dataset = generate_independent_dataset()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"✅ Generated {len(dataset)} independent human-labeled evaluation pairs at {out_path}")
