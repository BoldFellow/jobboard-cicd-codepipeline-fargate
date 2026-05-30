from dataclasses import dataclass


@dataclass
class Job:
    job_id: str
    title: str
    company: str = ""
    description: str = ""
    created_at: str = ""
    status: str = "open"


@dataclass
class Application:
    application_id: str
    job_id: str
    applicant_name: str
    applicant_email: str
    resume_summary: str = ""
    applied_at: str = ""
    status: str = "submitted"
