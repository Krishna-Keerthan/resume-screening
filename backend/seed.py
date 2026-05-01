"""
seeds.py — Populate the database with realistic fake data.

Usage:
    python seeds.py
    python seeds.py --clear
"""

import argparse
import json
import random
import uuid
import logging
from datetime import datetime, timedelta, timezone

from faker import Faker
from werkzeug.security import generate_password_hash

# ── Bootstrap Flask app ─────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.core.database import db
from app.models.candidate import Candidate
from app.models.recruiter import Recruiter
from app.models.job import Job
from app.models.resume import Resume
from app.models.application import Application
from app.models.ats_score import AtsScore
from app.models.refresh_token import RefreshToken

fake = Faker()
app = create_app("development")

# ── Config ──────────────────────────────────────────────────────────
N_CANDIDATES = 200
N_RECRUITERS = 20
N_JOBS = 100
DEFAULT_PASSWORD = "password123"

# Common skill pools for the templates
SKILLS_MAP = {
    "Frontend Developer": ["React", "TypeScript", "Next.js", "Tailwind CSS", "Redux", "Figma", "Sass", "GraphQL"],
    "Backend Developer": ["Python", "Flask", "PostgreSQL", "Redis", "Docker", "REST APIs", "AWS", "SQLAlchemy"],
    "AI/ML Engineer": ["PyTorch", "TensorFlow", "Scikit-learn", "Pandas", "Vector DBs", "NumPy", "HuggingFace"],
    "Full Stack Developer": ["React", "Node.js", "PostgreSQL", "Next.js", "TypeScript", "AWS", "Docker", "Express"],
    "DevOps Engineer": ["Kubernetes", "Docker", "Terraform", "CI/CD", "AWS", "Linux", "GitHub Actions", "Ansible"],
    "Data Scientist": ["Python", "SQL", "Tableau", "Pandas", "Statistics", "Machine Learning", "BigQuery"],
}

JOB_TITLES = list(SKILLS_MAP.keys())
INDUSTRIES = ["Technology", "Finance", "Healthcare", "Education", "E-commerce"]
COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "500+"]
JOB_TYPES = ["full-time", "part-time", "contract", "internship"]
JOB_STATUSES = ["active", "closed", "draft"]
APP_STAGES = ["applied", "reviewed", "shortlisted", "interviewing", "offered", "rejected", "hired"]

# ── Helpers ─────────────────────────────────────────────────────────
def _utc_now():
    return datetime.now(timezone.utc)

def _past(days=365):
    return _utc_now() - timedelta(days=random.randint(1, days))

def _future(days=90):
    return _utc_now() + timedelta(days=random.randint(1, days))

# ── Seeders ─────────────────────────────────────────────────────────

def seed_candidates():
    print(f"  Seeding {N_CANDIDATES} candidates...")
    objs = []
    pwd_hash = generate_password_hash(DEFAULT_PASSWORD)

    for _ in range(N_CANDIDATES):
        role = random.choice(JOB_TITLES)
        skills = SKILLS_MAP[role]
        
        objs.append(Candidate(
            id=str(uuid.uuid4()),
            full_name=fake.name(),
            email=fake.unique.email(),
            phone=fake.phone_number()[:30],
            location=f"{fake.city()}, {fake.country()}",
            headline=f"{role} | {random.randint(2, 8)}yrs exp | Open to new roles",
            password_hash=pwd_hash,
            linkedin_url=f"https://linkedin.com/in/{fake.user_name()}",
            github_url=f"https://github.com/{fake.user_name()}",
            portfolio_url=fake.url(),
            preferred_roles=json.dumps([role]),
            preferred_locations=json.dumps([fake.city(), "Remote"]),
            open_to_work=True,
            is_active=True,
            created_at=_past(500),
            updated_at=_past(100),
        ))

    db.session.add_all(objs)
    db.session.flush()
    return objs


def seed_recruiters():
    print(f"  Seeding {N_RECRUITERS} recruiters...")
    objs = []
    pwd_hash = generate_password_hash(DEFAULT_PASSWORD)

    for _ in range(N_RECRUITERS):
        objs.append(Recruiter(
            id=str(uuid.uuid4()),
            full_name=fake.name(),
            email=fake.unique.email(),
            company_name=fake.company(),
            industry=random.choice(INDUSTRIES),
            phone=fake.phone_number()[:30],
            password_hash=pwd_hash,
            company_size=random.choice(COMPANY_SIZES),
            website_url=fake.url(),
            linkedin_url=f"https://linkedin.com/company/{fake.slug()}",
            total_jobs_posted=random.randint(0, 10),
            total_hires=random.randint(0, 5),
            platform_rank=random.randint(80, 100),
            is_active=True,
            created_at=_past(500),
            updated_at=_past(100),
        ))

    db.session.add_all(objs)
    db.session.flush()
    return objs


def seed_jobs(recruiters):
    print(f"  Seeding {N_JOBS} jobs...")
    objs = []

    for _ in range(N_JOBS):
        r = random.choice(recruiters)
        role = random.choice(JOB_TITLES)
        skills = SKILLS_MAP[role]
        salary = random.randint(60, 150) * 1000

        description = (
            f"We are looking for a talented {role} to join our team at {r.company_name}. "
            f"Successful candidates will have strong experience with {', '.join(skills[:3])}. "
            f"You will be responsible for building scalable systems and working with cross-functional teams."
        )

        objs.append(Job(
            id=str(uuid.uuid4()),
            title=role,
            company=r.company_name,
            description=description,
            responsibilities=json.dumps([
                f"Develop and maintain high-performance {role.lower()} features.",
                f"Collaborate with stakeholders to define requirements.",
                f"Write clean, testable, and efficient code using {skills[0]}.",
                "Optimise application performance and scalability."
            ]),
            required_skills=json.dumps(skills),
            nice_to_have_skills=json.dumps(random.sample(SKILLS_POOL, 3) + ["Communication"]),
            experience_years=round(random.uniform(2, 6), 1),
            location=random.choice([fake.city(), "Remote", "Hybrid"]),
            job_type="full-time",
            status="active",
            salary_min=salary,
            salary_max=salary + 40000,
            salary_currency="USD",
            quality_score=random.uniform(0.8, 1.0),
            completeness_score=0.95,
            recruiter_id=r.id,
            applicant_count=0,
            is_deleted=False,
            created_at=_past(30),
            updated_at=_past(5),
        ))

    db.session.add_all(objs)
    db.session.flush()
    return objs


def seed_resumes(candidates):
    print("  Seeding resumes...")
    objs = []

    for c in candidates:
        # Extract role from headline (e.g. "Frontend Developer | ...")
        role = c.headline.split('|')[0].strip()
        skills = SKILLS_MAP.get(role, ["Python", "SQL"])
        
        raw_text = (
            f"{c.full_name}\n{role}\nEmail: {c.email}\n\nObjective:\n"
            f"Experienced {role} with a focus on building systems using {', '.join(skills)}.\n\n"
            f"Skills:\n- {', '.join(skills)}\n\nProfessional Experience:\n"
            f"Lead Developer at {fake.company()}\n"
            f"Worked extensively with {skills[0]} and {skills[1]} to deliver enterprise solutions."
        )

        objs.append(Resume(
            id=str(uuid.uuid4()),
            candidate_id=c.id,
            filename=f"resume_{fake.user_name()}.pdf",
            file_path=f"uploads/resume_{c.id[:8]}.pdf",
            file_size_kb=random.randint(100, 500),
            file_type="pdf",
            raw_text=raw_text,
            skills=json.dumps(skills),
            total_experience_years=float(c.headline.split('|')[1].split('yrs')[0].strip()),
            skill_count=len(skills),
            parse_status="success",
            is_active=True,
            is_deleted=False,
            created_at=_past(200),
            updated_at=_past(30),
        ))

    db.session.add_all(objs)
    db.session.flush()

    resume_map = {r.candidate_id: r for r in objs}
    return objs, resume_map


def seed_applications(candidates, jobs, resume_map):
    print("  Seeding applications...")
    objs = []
    used = set()

    for c in candidates:
        # Get target role for this candidate
        target_role = c.headline.split('|')[0].strip()
        
        # High chance of applying to jobs matching their role
        relevant_jobs = [j for j in jobs if j.title == target_role]
        selected_jobs = []
        
        # At least 1 matching job, plus 4-9 random ones for density
        if relevant_jobs:
            selected_jobs.append(random.choice(relevant_jobs))
        
        k_random = min(random.randint(4, 9), len(jobs))
        selected_jobs.extend(random.sample(jobs, k=k_random))

        for job in selected_jobs:
            key = (c.id, job.id)
            if key in used: continue
            used.add(key)

            resume = resume_map.get(c.id)
            if not resume: continue

            objs.append(Application(
                id=str(uuid.uuid4()),
                candidate_id=c.id,
                job_id=job.id,
                resume_id=resume.id,
                stage=random.choice(APP_STAGES),
                created_at=_past(60),
            ))
            # Manually increment the denormalized count on the Job object
            job.applicant_count += 1
            if job not in db.session:
                db.session.add(job)

    db.session.add_all(objs)
    db.session.flush()
    return objs


def seed_ats_scores(applications):
    print("  Seeding ATS scores...")
    objs = []

    for a in applications:
        # Determine if it's a match
        # (This is just for visual realism in the dashboard)
        # In a real run, the scorer would calculate these.
        is_match = random.choice([True, False, False]) # 33% chance of "good" match
        
        if is_match:
            s1 = random.uniform(0.7, 0.95)
            s2 = random.uniform(0.8, 0.98)
            s3 = random.uniform(0.6, 0.9)
            s4 = random.uniform(0.8, 1.0)
        else:
            s1 = random.uniform(0.2, 0.6)
            s2 = random.uniform(0.1, 0.5)
            s3 = random.uniform(0.2, 0.8)
            s4 = random.uniform(0.4, 0.7)

        final = round(s1*0.4 + s2*0.35 + s3*0.15 + s4*0.1, 3)
        
        objs.append(AtsScore(
            id=str(uuid.uuid4()),
            resume_id=a.resume_id,
            job_id=a.job_id,
            application_id=a.id,
            semantic_score=s1,
            keyword_score=s2,
            experience_score=s3,
            section_quality_score=s4,
            final_score=final,
            score_label=("excellent" if final >= .8 else "good" if final >= .65 else "fair" if final >= .5 else "weak"),
            created_at=a.created_at + timedelta(minutes=random.randint(1, 10)),
            updated_at=a.created_at + timedelta(minutes=random.randint(11, 20)),
        ))

    db.session.add_all(objs)
    db.session.flush()


# Global pools for report
SKILLS_POOL = [s for sublist in SKILLS_MAP.values() for s in sublist]

# ── Report Generation ──────────────────────────────────────────────────
def generate_report(candidates, recruiters):
    print("\n📝 Generating seed report...")
    report_path = "seed_report.md"
    
    with open(report_path, "w") as f:
        f.write("# 🛡️ Database Seed Report\n\n")
        f.write(f"**Generated At**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Default Password**: `{DEFAULT_PASSWORD}`\n\n")
        
        f.write("## 🏢 Recruiters (Top 10)\n")
        f.write("| Name | Email | Company |\n")
        f.write("| :--- | :--- | :--- |\n")
        for r in recruiters[:10]:
            f.write(f"| {r.full_name} | `{r.email}` | {r.company_name} |\n")
        
        f.write("\n## 👤 Candidates (Top 20)\n")
        f.write("| Name | Email | Headline |\n")
        f.write("| :--- | :--- | :--- |\n")
        for c in candidates[:20]:
            f.write(f"| {c.full_name} | `{c.email}` | {c.headline} |\n")
            
        f.write("\n\n> [!TIP]\n")
        f.write("> You can use these credentials to log in to the frontend at `http://localhost:3000/login`.\n")

    print(f"✅ Report saved to {report_path}")


# ── Clear DB ────────────────────────────────────────────────────────
def clear_all():
    print("  Clearing existing tables...")
    db.session.execute(db.text("""
        TRUNCATE TABLE refresh_tokens, ats_scores, applications,
        resumes, jobs, recruiters, candidates
        RESTART IDENTITY CASCADE;
    """))
    db.session.commit()


# ── Run ─────────────────────────────────────────────────────────────
def run_seeds(clear=False):
    with app.app_context():
        # Clear fake uniqueness
        try:
            fake.unique.clear()
        except AttributeError:
            pass

        if clear:
            clear_all()

        print("\n🌱 Starting Real-World Seeding...\n")

        try:
            c = seed_candidates()
            r = seed_recruiters()
            j = seed_jobs(r)
            resumes, resume_map = seed_resumes(c)
            apps = seed_applications(c, j, resume_map)

            seed_ats_scores(apps)
            
            db.session.commit()
            
            generate_report(c, r)
            
            print("\n✨ Seeding process completed successfully!\n")

        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Seeding Error: {e}")
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    run_seeds(clear=args.clear)