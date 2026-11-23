import uvicorn
import logging
import sys
from datetime import datetime
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

# Configure logging for the Job Portal Application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("JobPortal")

# Initialize the FastAPI application
app = FastAPI(title="TechCareers Job Portal")

# Mock database of active job listings
ACTIVE_JOBS = {
    "ENG-001": {"title": "Senior Frontend Engineer", "dept": "Engineering", "location": "Remote", "salary": "$130k - $160k"},
    "ENG-002": {"title": "Backend Python Developer", "dept": "Engineering", "location": "New York, NY", "salary": "$120k - $150k"},
    "DES-001": {"title": "UX/UI Designer", "dept": "Design", "location": "San Francisco, CA", "salary": "$110k - $140k"},
    "MKT-001": {"title": "Product Marketing Manager", "dept": "Marketing", "location": "Austin, TX", "salary": "$95k - $125k"}
}

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Landing page displaying all active job postings."""
    logger.info(f"Homepage accessed from {request.client.host}")
    
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>TechCareers - Find Your Dream Job</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; }
            .navbar { background-color: #005A9C; color: white; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; }
            .navbar h1 { margin: 0; font-size: 1.5rem; }
            .content { max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
            .job-card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 2px 5px rgba(0,0,0,0.05); border-left: 5px solid #005A9C; }
            .job-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
            .job-header h2 { margin: 0; color: #005A9C; font-size: 1.3rem; }
            .badge { background: #e9ecef; padding: 0.25rem 0.75rem; border-radius: 15px; font-size: 0.85rem; color: #495057; }
            .apply-btn { display: inline-block; margin-top: 1rem; padding: 0.5rem 1rem; background-color: #28a745; color: white; text-decoration: none; border-radius: 4px; font-weight: bold; }
            .apply-btn:hover { background-color: #218838; }
        </style>
    </head>
    <body>
        <div class="navbar">
            <h1>TechCareers Portal</h1>
            <div>Welcome, Guest</div>
        </div>
        <div class="content">
            <h2 style="margin-bottom: 1.5rem;">Open Positions</h2>
    """
    
    for job_id, details in ACTIVE_JOBS.items():
        html += f"""
            <div class="job-card">
                <div class="job-header">
                    <h2>{details['title']}</h2>
                    <span class="badge">{details['salary']}</span>
                </div>
                <p style="margin: 0.5rem 0; color: #666;">
                    <strong>Department:</strong> {details['dept']} &nbsp;|&nbsp; 
                    <strong>Location:</strong> {details['location']}
                </p>
                <a href="/apply?job_id={job_id}" class="apply-btn">Apply Now</a>
            </div>
        """
        
    html += """
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/apply", response_class=HTMLResponse)
async def application_form(job_id: str):
    """Returns the job application form for a specific job ID."""
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job = ACTIVE_JOBS[job_id]
    logger.info(f"Serving application form for job ID: {job_id}")
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Apply for {job['title']}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; }}
            .navbar {{ background-color: #005A9C; color: white; padding: 1rem 2rem; }}
            .form-container {{ max-width: 600px; margin: 2rem auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
            .form-group {{ margin-bottom: 1.5rem; }}
            .form-group label {{ display: block; margin-bottom: 0.5rem; font-weight: bold; color: #333; }}
            .form-group input, .form-group textarea {{ width: 100%; padding: 0.75rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; font-family: inherit; }}
            .submit-btn {{ width: 100%; padding: 1rem; background-color: #005A9C; color: white; border: none; border-radius: 4px; font-size: 1.1rem; cursor: pointer; }}
            .submit-btn:hover {{ background-color: #004080; }}
        </style>
    </head>
    <body>
        <div class="navbar">
            <h1 style="margin:0; font-size:1.5rem;">TechCareers Portal</h1>
        </div>
        <div class="form-container">
            <h2 style="margin-top:0; color:#005A9C;">Application: {job['title']}</h2>
            <form action="/preview_application" method="POST">
                <input type="hidden" name="job_id" value="{job_id}">
                
                <div class="form-group">
                    <label for="applicant_name">Full Name</label>
                    <input type="text" id="applicant_name" name="applicant_name" required>
                </div>
                
                <div class="form-group">
                    <label for="cover_letter">Cover Letter Snippet</label>
                    <textarea id="cover_letter" name="cover_letter" rows="5" placeholder="Tell us why you are a great fit..." required></textarea>
                </div>
                
                <button type="submit" class="submit-btn">Preview Application</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/preview_application", response_class=HTMLResponse)
async def preview_application(
    job_id: str = Form(...),
    applicant_name: str = Form(...),
    cover_letter: str = Form(...)
):
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via POST Form Data.
    
    This function processes an HTTP POST request containing form data 
    (application details). It extracts the 'applicant_name' and 'cover_letter' fields 
    and concatenates them directly into the HTML response structure without any 
    sanitization or HTML encoding.
    
    Trigger Path:
    1. An attacker crafts a malicious web page containing an auto-submitting form 
       targeting this endpoint via POST.
    2. The form contains malicious payloads in the 'applicant_name' or 'cover_letter' 
       fields (e.g., `<script>alert(document.domain)</script>`).
    3. The attacker tricks a logged-in user (like a recruiter or another user) into 
       visiting their malicious page (Cross-Site Request Forgery leading to XSS).
    4. The victim's browser submits the POST request. The server reflects the payload 
       directly into the HTML DOM of the preview page, executing the script in the 
       context of the vulnerable application.
    """
    logger.info(f"Generating application preview for candidate: {applicant_name}")
    
    job_title = ACTIVE_JOBS.get(job_id, {}).get("title", "Unknown Position")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # VULNERABLE SINK: The variables `applicant_name` and `cover_letter`, retrieved 
    # directly from the POST payload, are embedded into the HTML structure unescaped.
    html_preview = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Application Preview</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; }}
            .header-banner {{ background-color: #ffc107; color: #856404; padding: 1rem; text-align: center; font-weight: bold; border-bottom: 2px solid #ffeeba; }}
            .preview-container {{ max-width: 700px; margin: 2rem auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); border-top: 5px solid #005A9C; }}
            .section {{ margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid #eee; }}
            .section h3 {{ color: #005A9C; margin-top: 0; }}
            .data-row {{ margin-bottom: 0.5rem; }}
            .data-label {{ font-weight: bold; color: #555; display: inline-block; width: 120px; }}
            .warning {{ background-color: #f8d7da; color: #721c24; padding: 10px; border-radius: 4px; margin-top: 20px; }}
            .action-btn {{ display: inline-block; padding: 0.75rem 1.5rem; background-color: #005A9C; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="header-banner">
            PREVIEW MODE - Your application has NOT been submitted yet.
        </div>
        
        <div class="preview-container">
            <h2 style="text-align: center; margin-bottom: 2rem;">Application Summary</h2>
            
            <div class="section">
                <h3>Job Details</h3>
                <div class="data-row"><span class="data-label">Position:</span> {job_title}</div>
                <div class="data-row"><span class="data-label">Job ID:</span> {job_id}</div>
                <div class="data-row"><span class="data-label">Generated:</span> {current_time}</div>
            </div>
            
            <div class="section">
                <h3>Candidate Information</h3>
                <!-- XSS Injection Point 1 -->
                <div class="data-row"><span class="data-label">Name:</span> 
                    <span style="font-size: 1.1em; color: #000;">{applicant_name}</span>
                </div>
            </div>
            
            <div class="section" style="border-bottom: none;">
                <h3>Cover Letter Details</h3>
                <!-- XSS Injection Point 2 -->
                <div style="background: #f8f9fa; padding: 15px; border-radius: 4px; border-left: 4px solid #ced4da; white-space: pre-wrap;">{cover_letter}</div>
            </div>
            
            <div class="warning">
                Please review your details carefully. Once submitted, changes cannot be made.
            </div>
            
            <div style="margin-top: 2rem; text-align: center;">
                <a href="/apply?job_id={job_id}" style="background-color: #6c757d;" class="action-btn">Edit Details</a>
                <!-- Dummy submission action for demonstration -->
                <a href="/" style="background-color: #28a745;" class="action-btn">Confirm & Submit</a>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_preview)


if __name__ == "__main__":
    port = 8080
    logger.info(f"Starting Job Portal FastAPI Server on port {port}...")
    # Run the server using Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
