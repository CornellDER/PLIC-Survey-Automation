# PLIC Survey Automation

Five AWS Lambda functions that automate the PLIC assessment survey lifecycle — survey creation, pre/post date management, scheduled reminders, and scored data uploads to S3 — integrated with Qualtrics and a Streamlit dashboard.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Lambda Functions — Detailed Reference](#lambda-functions--detailed-reference)
- [S3 Buckets](#s3-buckets)
- [Qualtrics Integration](#qualtrics-integration)
- [Email Templates](#email-templates)
- [Environment Variables — Complete Reference](#environment-variables--complete-reference)
- [Deployment Notes](#deployment-notes)
- [Typical Survey Lifecycle](#typical-survey-lifecycle)
- [Troubleshooting](#troubleshooting)
- [File Structure](#file-structure)
- [Acknowledgements](#acknowledgements)


---

## Overview

This system automates the lifecycle of PLIC (Physics Lab Inventory of Critical thinking) assessment surveys. It consists of five AWS Lambda functions that interact with the Qualtrics survey platform, store tracking and results data in Amazon S3, and ultimately feed a Streamlit dashboard used for data exploration and reporting.

Unlike single-survey assessments, PLIC uses a **pre/post design**: each instructor gets two surveys (a pre-instruction survey and a post-instruction survey), both created from the same QSF template. The automation manages both surveys' lifecycles independently, including separate close dates, reminders, and closing logic.

---

## Architecture

```
Instructor (via Qualtrics CIS)
        │
        ▼
┌──────────────────┐
│  createPLICSurvey │──── Creates a new PLIC survey from QSF template in Qualtrics
└──────────────────┘
        │
        ▼
┌────────────────────┐
│  update_inprogress  │──── Adds class to in-progress tracking CSV in S3
└────────────────────┘
        │
        ▼
┌──────────────────┐
│  changePLICDates  │──── Lets instructors change close dates / reminders
└──────────────────┘
        │
        ▼
┌────────────────┐
│  automatePLIC   │──── Monitors active surveys: sends memos, survey links,
└────────────────┘     reminders, closes surveys, triggers data upload
        │              (runs on a schedule via EventBridge)
        ▼
┌───────────────────────┐
│  uploadDashboardData   │──── Scores responses, matches pre/post, uploads to S3
└───────────────────────┘
        │
        ▼
   S3 Dashboard Bucket  ──── Consumed by Streamlit dashboard
```

### How Data Flows

1. An instructor fills out the **Course Information Survey (CIS)** in Qualtrics, providing course details (institution, course name/number, class size, close dates, etc.).
2. **createPLICSurvey** generates a new PLIC survey from the `plicsurvey.qsf` template and returns a survey ID and link. This is called twice per instructor (once for pre-survey, once for post-survey).
3. **update_inprogress** adds the instructor's class ID to a tracking CSV in S3 so the automation knows to monitor it.
4. **changePLICDates** allows instructors to adjust their survey close dates or toggle reminders on/off for either the pre- or post-survey.
5. **automatePLIC** runs on a schedule (via AWS EventBridge). Each invocation, it reads the in-progress CSV and processes one action for one active survey:
   - **16 days before post-survey close**: Sends a memo email about the upcoming post-survey.
   - **14 days before post-survey close**: Sends the post-survey link to the instructor.
   - **4 days before close** (pre or post): Sends a reminder email (if reminders are enabled).
   - **Close date has passed** (pre-survey): Closes the survey in Qualtrics, sends a "survey closed" email.
   - **Close date has passed** (post-survey): Closes the survey, triggers data upload, sends a "report ready" email.
6. **uploadDashboardData** downloads all responses from Qualtrics for both pre- and post-surveys, validates them (consent, age, completeness, time-on-page), scores them against PLIC question weights, calculates constructs (models, methods, actions, attitudes), matches pre/post responses by student name and ID, and uploads the processed data to the dashboard S3 bucket.
7. The **Streamlit dashboard** (hosted at `plicdashboard.streamlit.app`) reads the processed CSV files from S3 to display results.

---

## Lambda Functions — Detailed Reference

### 1. automatePLIC

**Trigger:** Scheduled (AWS EventBridge / CloudWatch Events)

**Qualtrics workflow connection:** Calls **Workflow 2 ("Send Requested Email")** via the `EMAIL_REQUEST_URL` to send all automated emails (memos, survey links, reminders, survey-closed notifications, and report-ready notifications). The Lambda constructs the email content and posts it as a JSON payload to the workflow's trigger URL.

**Purpose:** The core automation engine. Runs periodically to monitor all active surveys and take action based on their close dates. Processes one action per invocation to stay within Lambda time limits and avoid overloading the Qualtrics API.

**What it does each invocation:**
1. Downloads the in-progress CSV from S3 to get the list of active class IDs.
2. Iterates through class IDs and retrieves each instructor's CIS response from Qualtrics.
3. Checks both pre-survey and post-survey close dates against today, with pre-survey checks taking priority:

**Pre-survey actions (if a pre-survey exists):**
- **Close date has passed** -> Closes the survey in Qualtrics, sends a "survey closed" email, updates the CIS response with timestamps.
- **Close date is within 4 days** -> Sends a reminder email (if reminders are enabled), updates the CIS response to record that the reminder was sent.

**Post-survey actions (checked after pre-survey is handled):**
- **Close date has passed** -> Closes the survey, calls `uploadDashboardData` via HTTP, sends a "report ready" email, updates the CIS response with timestamps.
- **Close date is within 4 days** -> Sends a reminder email (if reminders are enabled).
- **Close date is within 14 days** -> Sends the post-survey link to the instructor.
- **Close date is within 16 days** -> Sends a memo email about the upcoming post-survey.

4. Stops after handling one action (via `break`) to keep execution time low. This is compensated for by running the function on a frequent schedule.

**Catch-up behavior:** If earlier lifecycle steps were missed (e.g., the memo wasn't sent before the survey link email was needed), the function sets all skipped tracking fields to the current date in a single update. This prevents re-triggering of missed steps on future invocations.

**Source files:**

| File | Purpose |
|------|---------|
| `lambda_function.py` | Main handler — reads in-progress CSV, date logic, orchestration |
| `utilities/qualtrics_utils.py` | `get_response_count()`, `get_response_data()`, `update_response_data()`, `close_survey()` |
| `utilities/email_utils.py` | `send_email()`, `build_email()` — constructs and sends emails via Qualtrics |
| `utilities/memo.txt` | Email template for upcoming post-survey memo |
| `utilities/survey_sent.txt` | Email template for sending the survey link |
| `utilities/reminder.txt` | Email template for survey reminders (includes response count, close date, survey link) |
| `utilities/survey_closed.txt` | Email template for pre-survey close notification |
| `utilities/report_sent.txt` | Email template for report-ready notification (includes dashboard link) |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `QUALTRICS_API_TOKEN` | API token for authenticating with Qualtrics |
| `QUALTRICS_BASE_URL` | Qualtrics datacenter base URL (e.g., `https://cornell.ca1.qualtrics.com`) |
| `CIS_SURVEY_ID` | Survey ID of the Course Information Survey in Qualtrics |
| `EXPECTED_TOKEN` | Shared API key used to authenticate inter-service calls |
| `INPROGRESS_BUCKET_NAME` | S3 bucket name containing the in-progress tracking CSV |
| `INPROGRESS_FILE_NAME` | Filename of the in-progress CSV (e.g., `in_progress.csv`) |
| `EMAIL_REQUEST_URL` | Qualtrics Workflow trigger URL for sending emails |

**Hardcoded values:**

| Value | Location | Description |
|-------|----------|-------------|
| `https://ao2r2skkh2.execute-api.us-east-2.amazonaws.com/default/uploadDashboardData` | `lambda_function.py` line 24 | API Gateway URL for calling `uploadDashboardData` |
| `https://cornell.ca1.qualtrics.com/jfe/form/SV_3EHa64tHQIJZQEu` | `email_utils.py` line 83 | Date change form URL embedded in email templates |
| `plicdashboard.streamlit.app` | `email_utils.py` line 85 | Dashboard URL embedded in report-ready emails |

---

### 2. createPLICSurvey

**Trigger:** API Gateway (HTTP POST)

**Qualtrics workflow connection:** Called by **Workflow 1 ("Create All Requested Surveys")** as T-ID 1 (post-survey, SurveyType=`POST`) and T-ID 2 (pre-survey, SurveyType=`Pre`) when an instructor submits the Course Information Survey. The workflow passes in institution, instructor name, course number, semester, and survey type, and receives back a `surveyId` and `surveyLink`.

**Purpose:** Creates a new PLIC survey in Qualtrics from the `plicsurvey.qsf` template. Returns the new survey's ID and link so the instructor can distribute it to students. Called once per survey (separately for pre and post).

**What it does:**
1. Validates the API token from request headers.
2. Extracts survey parameters from the request body: semester, institution, course number, instructor last name, survey type (PRE/POST), and instructor ID.
3. Sanitizes all text inputs (normalizes Unicode to ASCII, removes special characters, replaces spaces with underscores, truncates to max length).
4. Generates a survey title in the format: `{Semester}{Year}_{Institution}_{CourseNumber}_{LastName}_{SurveyType}_{InstructorID}`
5. Loads the `plicsurvey.qsf` template file.
6. Sets the survey name inside the QSF JSON.
7. Creates the survey in Qualtrics via the Survey Definitions API endpoint.
8. Activates the newly created survey.
9. Returns the survey ID and a direct survey link.

**Request body fields:**

| Field | Description | Example |
|-------|-------------|---------|
| `Semester` | Semester code | `"FA"`, `"SP"`, `"SU"` |
| `Institution` | Name of the institution | `"Cornell_University"` |
| `Number` | Course number or identifier | `"PHYS101"` |
| `InstructorLast` | Instructor's last name | `"Smith"` |
| `SurveyType` | Pre- or post-instruction | `"PRE"` or `"POST"` |
| `Instructor_ID` | Unique instructor identifier from CIS (Qualtrics response ID) | `"R_abc123"` |

**Source files:**

| File | Purpose |
|------|---------|
| `lambda_function.py` | Main handler — input validation, Qualtrics API calls, survey creation |
| `plicsurvey.qsf` | QSF template for all PLIC surveys (single template for both pre and post) |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `QUALTRICS_API_TOKEN` | API token for authenticating with Qualtrics |
| `QUALTRICS_BASE_URL` | Qualtrics datacenter base URL |
| `CIS_SURVEY_ID` | Course Information Survey ID |
| `EXPECTED_TOKEN` | API key for request validation |

---

### 3. changePLICDates

**Trigger:** API Gateway (HTTP POST)

**Qualtrics workflow connection:** Called by **Workflow 3 ("Update Close Dates, Update CIS, and Send Email")** as T-ID 1 when an instructor submits the `PLIC_Date_Changes_2` form. The workflow passes in the requested close dates and reminder preferences, and receives back instructor details, a JSON payload for updating the CIS, and `PRE Update Possible` / `POST Update Possible` flags.

**Purpose:** Allows instructors to modify the close date and reminder preferences for their pre-survey, post-survey, or both. If a survey was previously closed, this function reactivates it and re-adds the class to in-progress tracking.

**What it does:**
1. Validates the API token from request headers.
2. Extracts the instructor ID, new close dates, and reminder preferences from the request body.
3. Looks up the instructor's CIS response in Qualtrics to get the associated survey IDs.
4. For each survey (pre and/or post) where a new close date is provided:
   - Sets the new close date in the CIS embedded data.
   - If the survey was previously closed, reactivates it via the Qualtrics API.
   - Adds the class ID to the in-progress tracking CSV in S3 (if not already present).
   - Clears the "Closed" and "Report Sent" fields so automation picks it up again.
   - Handles reminder preference: sets to `None` (will send reminder) or current date (won't send reminder).
5. Returns instructor details, update status flags, and a JSON payload for Qualtrics Workflows to update the CIS.

**Request body fields:**

| Field | Description |
|-------|-------------|
| `Instructor_ID` | Instructor's CIS response ID |
| `Requested Pre-Survey Close Date` | New pre-survey close date (YYYY/MM/DD) |
| `Requested Pre-Survey Reminder` | Whether to send pre-survey reminders (`"Yes"` or `"No"`) |
| `Requested Post-Survey Close Date` | New post-survey close date (YYYY/MM/DD) |
| `Requested Post-Survey Reminder` | Whether to send post-survey reminders (`"Yes"` or `"No"`) |

**Source files:**

| File | Purpose |
|------|---------|
| `lambda_function.py` | Main handler — date updates, survey reactivation, CSV tracking |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `QUALTRICS_API_TOKEN` | API token for authenticating with Qualtrics |
| `QUALTRICS_BASE_URL` | Qualtrics datacenter base URL |
| `CIS_SURVEY_ID` | Course Information Survey ID |
| `EXPECTED_TOKEN` | API key for request validation |
| `INPROGRESS_BUCKET_NAME` | S3 bucket for in-progress tracking |
| `INPROGRESS_FILE_NAME` | In-progress CSV filename |

---

### 4. update_inprogress

**Trigger:** API Gateway (HTTP POST)

**Qualtrics workflow connection:** Called by **Workflow 1 ("Create All Requested Surveys")** as T-ID 7 when an instructor submits the Course Information Survey. The workflow passes in the instructor's Response ID to add the class to the in-progress tracking CSV.

**Purpose:** Adds a class/instructor to the in-progress tracking CSV. Used when a survey is created or managed outside the normal automated workflow and needs to be picked up by `automatePLIC`.

**What it does:**
1. Validates the API token from request headers.
2. Extracts the instructor ID from the request body.
3. Downloads the in-progress CSV from S3.
4. Checks if the class ID already exists (skips if duplicate).
5. Appends the new class ID as a row.
6. Uploads the updated CSV back to S3.

**Request body fields:**

| Field | Description |
|-------|-------------|
| `Instructor_ID` | Instructor's CIS response ID to add to tracking |

**Source files:**

| File | Purpose |
|------|---------|
| `lambda_function.py` | Main handler — CSV read/update/upload logic |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `EXPECTED_TOKEN` | API key for request validation |
| `CIS_SURVEY_ID` | Course Information Survey ID |
| `INPROGRESS_BUCKET_NAME` | S3 bucket for in-progress tracking |
| `INPROGRESS_FILE_NAME` | In-progress CSV filename |

---

### 5. uploadDashboardData

**Trigger:** API Gateway (HTTP POST) or called internally by `automatePLIC`

**Qualtrics workflow connection:** Not called directly by a Qualtrics workflow. Invoked by `automatePLIC` via HTTP when a post-survey closes, or can be called manually via the API Gateway endpoint.

**Purpose:** The data processing pipeline. Downloads raw survey responses from Qualtrics for both pre- and post-surveys, validates and filters them, scores student answers using PLIC question weights, matches pre/post responses by student identity, and uploads the processed results to S3 for the Streamlit dashboard.

**What it does:**
1. Validates the API token from request headers.
2. Retrieves the instructor's CIS response to determine the post-survey ID, pre-survey ID (if any), course type, and class size.
3. **Downloads and processes the post-survey** (always present):
   - Exports responses from Qualtrics (creates export, polls until complete, downloads ZIP, extracts CSV).
   - Validates responses (see Validation Rules below).
   - Scores individual PLIC questions using weighted scoring.
   - Calculates PLIC constructs (models, methods, actions) and attitude constructs (self-efficacy, perceived agency, belonging, recognition).
4. **Downloads and processes the pre-survey** (if it exists):
   - Same validation and scoring pipeline as the post-survey.
5. **Matches pre/post responses** by student identity:
   - Merges on full name (last + first), reversed name (first + last), and student ID.
   - Unmatched pre-only and post-only responses are preserved in the output.
   - All columns receive `_PRE` or `_POST` suffixes.
6. **Simplifies and reorders columns** based on `ColumnOrdering_June2025.csv`:
   - Renames numbered task preference/done/role distribution columns to descriptive names.
   - Adds metadata columns: `Class_ID`, `Course Type`, `Class_Size`, `PLIC_Version`.
   - Maps course type codes (1 = Introductory, 2 = Beyond Introductory).
7. **Uploads** the processed DataFrame to S3:
   - Filename format: `{DASHBOARD_KEY}_{year}.csv`
   - Appends to existing data if the file already exists.
   - Removes duplicate Class_ID entries to handle survey reopenings cleanly.
8. **Removes** the class ID from the in-progress tracking CSV.

**Validation rules (applied to both pre and post responses):**

| Rule | Implementation |
|------|----------------|
| Consent required | `QConsent == 1` |
| Must be 18+ | `Q6d == 2` |
| Survey must be completed | `Finished == 1` |
| Minimum engagement | At least 30 seconds spent on at least one page (`Qt1_3`, `Qt2_3`, `Qt3_3`, or `Qt4_3` >= 30) |
| Identification required | At least one of `QStudentID`, `QLastName`, or `QFirstName` must be non-null |
| No duplicates | Duplicate entries by full name or student ID are dropped |

**PLIC scoring details:**

The PLIC has 8 scored questions: Q1b, Q2b, Q3b, Q3d, Q4b, Q1e, Q2e, Q3e.

- **Q1b, Q2b, Q3b** have special handling: contradictory response pairs are merged (if either item in a pair is selected, the pair counts as selected). Students can select at most 2 items, and scoring is normalized by the density of selected items.
- **Q3d, Q4b, Q1e, Q2e, Q3e** are scored directly using weights from `QuestionText_June2025.csv`, normalized by the density of selected items.

**Construct scoring:**

| Construct | Questions | Notes |
|-----------|-----------|-------|
| `models` | Q1B, Q2B, Q3B, Q3D | Mean of question scores |
| `methods` | Q4B | Single question |
| `actions` | Q1E, Q2E, Q3E | Mean of question scores |
| `TotalScore` | All 8 questions | Sum of all question scores |
| `NormScore` | All 8 questions | TotalScore / 8 |
| `SelfEfficacy` | QDem_SE_1 through QDem_SE_10 | Mean; requires all items present |
| `PerceivedAgency` | QDem_Constructs_QDem_PA_1 through _4 | Mean; requires all items present |
| `Belonging` | QDem_Constructs_QDem_Bel_1 through _6 | Mean with reverse coding on items 1, 3, 5, 6 (formula: 6 - value); requires all items present |
| `Recognition` | QDem_Constructs_QDem_Rec_1 through _4 | Mean; requires all items present |

**Source files:**

| File | Purpose |
|------|---------|
| `lambda_function.py` | Main handler — orchestration, S3 upload, in-progress cleanup |
| `utilities/compiling_utils.py` | `compile_course_data()` — orchestrates the full data pipeline |
| `utilities/qualtrics_utils.py` | `get_cis_response_data()`, `download_responses_as_df()` — Qualtrics data retrieval |
| `utilities/scoring_utils.py` | `validate_responses()`, `score_plic_questions()`, `score_constructs()` — validation and scoring |
| `utilities/processing_utils.py` | `process_names()`, `match_responses()`, `simplify_columns()` — name processing, pre/post matching, column cleanup |
| `utilities/QuestionText_June2025.csv` | PLIC question weights for scoring |
| `utilities/ColumnOrdering_June2025.csv` | Final column ordering for dashboard output |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `QUALTRICS_API_TOKEN` | API token for authenticating with Qualtrics |
| `QUALTRICS_BASE_URL` | Qualtrics datacenter base URL |
| `CIS_SURVEY_ID` | Course Information Survey ID |
| `EXPECTED_TOKEN` | API key for request validation |
| `DASHBOARD_BUCKET_NAME` | S3 bucket where processed dashboard data is stored |
| `DASHBOARD_KEY` | Base key name for dashboard CSV (year is appended: `{key}_{year}.csv`) |
| `INPROGRESS_FILE_NAME` | In-progress CSV filename (in the dashboard bucket) |

---

## S3 Buckets

| Bucket (env var) | Contents | Used By |
|------------------|----------|---------|
| `INPROGRESS_BUCKET_NAME` | `in_progress.csv` — tracks active class IDs with surveys currently open | automatePLIC (read), changePLICDates (write), update_inprogress (write), uploadDashboardData (write) |
| `DASHBOARD_BUCKET_NAME` | `{DASHBOARD_KEY}_{Year}.csv` — scored and processed survey results | uploadDashboardData (write), Streamlit dashboard (read) |

### In-Progress CSV Format

| Column | Description |
|--------|-------------|
| `Class_ID` | The instructor's CIS response ID, used to look up all related survey data |

### Dashboard CSV Format

The output columns are defined by `ColumnOrdering_June2025.csv` and include:

- `Class_ID` — Identifier linking to the CIS response
- `Course Type` — Introductory or Beyond Introductory
- `Class_Size` — Reported class enrollment
- `PLIC_Version` — Version of the PLIC instrument (e.g., `June2025`)
- `StudentID`, `LastName`, `FirstName` — Student identification (consolidated from pre/post)
- Individual PLIC question scores with `_PRE` and `_POST` suffixes
- Construct scores (`models`, `methods`, `actions`, `TotalScore`, `NormScore`) with `_PRE` and `_POST` suffixes
- Attitude constructs (`SelfEfficacy`, `PerceivedAgency`, `Belonging`, `Recognition`) with `_PRE` and `_POST` suffixes
- Task preference, task done, and role distribution fields with `_PRE` and `_POST` suffixes
- Demographic fields with `_PRE` and `_POST` suffixes

---

## Qualtrics Integration

### Course Information Survey (CIS)

The CIS is a central Qualtrics survey that stores instructor and course metadata as embedded data fields. Its survey ID is configured via the `CIS_SURVEY_ID` environment variable. Every function references the CIS to look up or update instructor data.

Key embedded data fields stored in CIS responses:

| Field | Description |
|-------|-------------|
| `Pre-Survey ID` | Qualtrics survey ID for the instructor's pre-instruction PLIC |
| `Post-Survey ID` | Qualtrics survey ID for the instructor's post-instruction PLIC |
| `Pre-Survey Close Date` | When the pre-survey should close (YYYY/MM/DD) |
| `Post-Survey Close Date` | When the post-survey should close (YYYY/MM/DD) |
| `Pre-Survey Reminder` | Date the pre-survey reminder was sent (empty = not sent) |
| `Post-Survey Reminder` | Date the post-survey reminder was sent (empty = not sent) |
| `Pre-Survey Closed` | Date the pre-survey was closed (empty = still open) |
| `Post-Survey Closed` | Date the post-survey was closed (empty = still open) |
| `Post-Survey Sent` | Date the post-survey link was sent (empty = not sent) |
| `Post-Survey Memo` | Date the post-survey memo was sent (empty = not sent) |
| `Report Sent` | Date the report-ready notification was sent (empty = not sent) |
| `QID2_TEXT` | Instructor first name |
| `QID59_TEXT` | Instructor last name |
| `QID3_TEXT` | Instructor email address |
| `QID9_TEXT` | Course name |
| `QID10_TEXT` | Course number |
| `QID11` | Course type (1 = Introductory, 2 = Beyond Introductory) |
| `QID12_TEXT` | Class size |

### API Authentication

All Qualtrics API calls use a bearer token (`QUALTRICS_API_TOKEN`) in the `X-API-TOKEN` header. The base URL (`QUALTRICS_BASE_URL`) varies by Qualtrics datacenter.

### Inter-Function Authentication

All Lambda functions validate incoming requests using a shared token (`EXPECTED_TOKEN`) passed in the `x-api-key` request header. Requests without a valid token are rejected with a 403 response.

### Qualtrics Workflows

Three workflows orchestrate the handoff between Qualtrics and the AWS Lambda functions. Two are on the `Course_Information_Survey_2` survey, and one is on the `PLIC_Date_Changes_2` survey.

#### Workflow 1: "Create All Requested Surveys" (on Course_Information_Survey_2)

**Trigger:** A new response is created on `Course_Information_Survey_2` (newly created responses only — not API updates, imported responses, or incomplete responses).

This workflow runs automatically when an instructor submits the CIS. It creates the surveys, adds the class to tracking, then branches based on whether the instructor requested only a post-survey or both pre- and post-surveys (determined by the embedded data field `NumSurveys`).

```
Instructor submits CIS
        │
        ▼
┌───────────────────────────────────────┐
│  T-ID 1: Create Post-PLIC Survey      │
│  POST → createPLICSurvey              │
│  SurveyType = POST                    │
│  Returns: postSurveyId, postSurveyLink │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  T-ID 7: Add course ID to InProgress  │
│  POST → update_inprogress             │
│  Sends: Instructor_ID                 │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  Decision: NumSurveys == 1?            │
└───────────────────────────────────────┘
       ╱ ╲
      ╱   ╲
  Branch 1           Otherwise
  (Post only)        (Pre + Post)
     │                    │
     ▼                    ▼
┌───────────┐    ┌───────────────────────────────────────┐
│ T-ID 5:   │    │  T-ID 2: Create Pre-PLIC Survey       │
│ Email     │    │  POST → createPLICSurvey              │
│ (post-    │    │  SurveyType = Pre                     │
│  survey   │    │  Returns: preSurveyId, preSurveyLink  │
│  link)    │    └───────────────────────────────────────┘
└───────────┘             │
     │                    ▼
     ▼             ┌───────────┐
┌───────────┐      │ T-ID 6:   │
│ T-ID 3:   │      │ Email     │
│ Update    │      │ (pre-     │
│ CIS Data  │      │  survey   │
└───────────┘      │  link)    │
     │             └───────────┘
     ▼                    │
 End of                   ▼
 workflow          ┌───────────┐
                   │ T-ID 4:   │
                   │ Update    │
                   │ CIS Data  │
                   └───────────┘
                        │
                        ▼
                    End of
                    workflow
```

**Task details:**

| Step | Type | Target | What it does |
|------|------|--------|-------------|
| T-ID 1 | WebService (POST) | `createPLICSurvey` Lambda | Creates the **post-survey**. Sends Institution, InstructorLast, Instructor_ID, Number, Semester, SurveyType=`POST`. Returns `postSurveyId` and `postSurveyLink`, piped into later tasks. |
| T-ID 7 | WebService (POST) | `update_inprogress` Lambda | Passes the instructor's Response ID as `Instructor_ID` to add the class to the in-progress tracking CSV. |
| Decision | Conditional | — | Checks embedded data `NumSurveys`. **Branch 1** (`NumSurveys == 1`): instructor requested post-survey only. **Otherwise**: instructor requested both pre- and post-surveys. |
| T-ID 2 | WebService (POST) | `createPLICSurvey` Lambda | *(Otherwise branch only)* Creates the **pre-survey**. Same parameters as T-ID 1 but SurveyType=`Pre`. Returns `preSurveyId` and `preSurveyLink`. |
| T-ID 5 | Email | Instructor | *(Branch 1 only)* Sends the **post-survey link** to the instructor (see email template below). |
| T-ID 6 | Email | Instructor | *(Otherwise branch only)* Sends the **pre-survey link** to the instructor (see email template below). |
| T-ID 3 | WebService (PUT) | Qualtrics API (`/API/v3/responses/{ResponseID}`) | *(Branch 1 only)* Updates the CIS response's embedded data: sets `Post-Survey ID` (from T-ID 1), `Post-Survey Sent`, `Survey Creation Date`, and `Post-Survey Memo` to the current date. |
| T-ID 4 | WebService (PUT) | Qualtrics API (`/API/v3/responses/{ResponseID}`) | *(Otherwise branch only)* Updates the CIS response's embedded data: sets `Post-Survey ID` (from T-ID 1), `Pre-Survey ID` (from T-ID 2), `Pre-Survey Sent`, and `Survey Creation Date` to the current date. |

**WebService parameters for T-ID 1 and T-ID 2:**

| Body Field | Value | Source |
|------------|-------|--------|
| `Institution` | `${q://QID5/ChoiceTextEntryValue}` | CIS answer |
| `InstructorLast` | `${q://QID59/ChoiceTextEntryValue}` | CIS answer |
| `Instructor_ID` | `${rm://Field/ResponseID}` | Qualtrics response ID |
| `Number` | `${q://QID10/ChoiceTextEntryValue}` | CIS answer |
| `Semester` | `${e://Field/Season}` | CIS embedded data |
| `SurveyType` | `POST` (T-ID 1) or `Pre` (T-ID 2) | Hardcoded |

**T-ID 3 JSON body (Branch 1 — post-survey only):**

```json
{
  "surveyId": "SV_0jlsamgr7VAmvum",
  "resetRecordedDate": true,
  "embeddedData": {
    "Post-Survey ID": "~{ch://OCAC_PMwU6tiyfioHdNG/$.surveyId}",
    "Post-Survey Sent": "${date://CurrentDate/Y%2Fm%2Fd}",
    "Survey Creation Date": "${date://CurrentDate/Y%2Fm%2Fd}",
    "Post-Survey Memo": "${date://CurrentDate/Y%2Fm%2Fd}"
  }
}
```

Note: `Post-Survey Sent` and `Post-Survey Memo` are set to the current date immediately because with no pre-survey phase, those lifecycle steps are skipped — this prevents `automatePLIC` from re-triggering them.

**T-ID 4 JSON body (Otherwise — pre- and post-survey):**

```json
{
  "surveyId": "SV_0jlsamgr7VAmvum",
  "resetRecordedDate": true,
  "embeddedData": {
    "Post-Survey ID": "~{ch://OCAC_PMwU6tiyfioHdNG/$.surveyId}",
    "Pre-Survey ID": "~{ch://OCAC_O49flTfIsSnLcY1/$.surveyId}",
    "Pre-Survey Sent": "${date://CurrentDate/Y%2Fm%2Fd}",
    "Survey Creation Date": "${date://CurrentDate/Y%2Fm%2Fd}"
  }
}
```

Note: `Pre-Survey Sent` is set to the current date because the pre-survey link is emailed to the instructor immediately (via T-ID 6).

**T-ID 5 email (Branch 1 — post-survey link):**

| Field | Value |
|-------|-------|
| **To** | `${q://QID3/ChoiceTextEntryValue}` (instructor email) |
| **From** | CPERL@cornell.edu (display name: "Cornell Physics Education Research Lab") |
| **Reply-To** | CPERL@cornell.edu |
| **Subject** | `PLIC Post-Survey link (${rm://Field/ResponseID})` |

> Dear Dr. ${q://QID2/ChoiceTextEntryValue} ${q://QID59/ChoiceTextEntryValue},
>
> Thank you for participating in the PLIC survey. Below is the link to the post-survey for your course, ${q://QID9/ChoiceTextEntryValue} (${q://QID10/ChoiceTextEntryValue}):
>
> ~{ch://OCAC_PMwU6tiyfioHdNG/$.surveyLink}
>
> Please share this link with your students at least 7 days before the close date listed below.
>
> This link is currently active and will remain active until:
> ${q://QID18/ChoiceTextEntryValue}
>
> If you would like to change the date that the survey will stop accepting responses from students, please complete the form here with your unique ID (${rm://Field/ResponseID}):
>
> https://cornell.ca1.qualtrics.com/jfe/form/SV_3INpKjeS7Mjss06
>
> Let us know by replying to this email if you have any questions about this process.
>
> Thank you,
> Cornell Physics Education Research Lab
>
> This message was sent by an automated system.

**T-ID 6 email (Otherwise — pre-survey link):**

| Field | Value |
|-------|-------|
| **To** | `${q://QID3/ChoiceTextEntryValue}` (instructor email) |
| **From** | CPERL@cornell.edu (display name: "Cornell Physics Education Research Lab") |
| **Reply-To** | CPERL@cornell.edu |
| **Subject** | `PLIC Pre-Survey link (${rm://Field/ResponseID})` |

> Dear Dr. ${q://QID2/ChoiceTextEntryValue} ${q://QID59/ChoiceTextEntryValue},
>
> Thank you for participating in the PLIC survey. Below is the link to the pre-survey for your course, ${q://QID9/ChoiceTextEntryValue} (${q://QID10/ChoiceTextEntryValue}):
>
> ~{ch://OCAC_O49flTfIsSnLcY1/$.surveyLink}
>
> Please share this link with your students at least 7 days before the close date listed below.
>
> This link is currently active and will remain active until:
> ${q://QID17/ChoiceTextEntryValue}
>
> If you would like to change the date that the survey will stop accepting responses from students, please complete the form here with your unique ID (${rm://Field/ResponseID}):
>
> https://cornell.ca1.qualtrics.com/jfe/form/SV_3INpKjeS7Mjss06
>
> Let us know by replying to this email if you have any questions about this process.
>
> Thank you,
> Cornell Physics Education Research Lab
>
> This message was sent by an automated system.

#### Workflow 2: "Send Requested Email" (on Course_Information_Survey_2)

**Trigger:** JSON inbound event via trigger URL (called by `automatePLIC` Lambda).

This is a simple email relay — the Lambda constructs the full email content and posts it to the Qualtrics trigger URL, which sends the email. This workflow is used to send all automated emails: memos, survey links, reminders, survey-closed notifications, and report-ready notifications.

```
automatePLIC Lambda
        │
        ▼
┌──────────────────────────────┐
│  JSON Trigger                 │
│  "AWS Requests Email with     │
│   JSON Trigger"               │
│  Receives: emailAddress,      │
│  emailSubject, emailBody      │
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  T-ID 1: Send Requested Email │
│  From: CPERL@cornell.edu      │
│  (Cornell Physics Education    │
│   Research Lab)                │
│  To/Subject/Body from trigger  │
└──────────────────────────────┘
        │
        ▼
    End of workflow
```

**Trigger details:**

| Field | Value |
|-------|-------|
| **Trigger URL** | `https://yul1.qualtrics.com/inbound-event/v1/events/json/triggers?urlTokenId=1b437...` (this is the `EMAIL_REQUEST_URL` environment variable in `automatePLIC`) |
| **Authentication** | Required by Qualtrics (toggle enabled) |
| **JSON fields** | `emailAddress` (`$.emailAddress`), `emailSubject` (`$.emailSubject`), `emailBody` (`$.emailBody`) |

**T-ID 1 — Email task:**

| Field | Source |
|-------|--------|
| **To** | `~{aedj://emailAddress}` (from JSON trigger payload) |
| **From** | CPERL@cornell.edu (display name: "Cornell Physics Education Research Lab") |
| **Reply-To** | CPERL@cornell.edu |
| **Subject** | `~{aedj://emailSubject}` (from JSON trigger payload) |
| **Body** | `~{aedj://emailBody}` (from JSON trigger payload) |

The email templates are defined in `automatePLIC/utilities/` (`memo.txt`, `survey_sent.txt`, `reminder.txt`, `survey_closed.txt`, `report_sent.txt`). The Lambda reads the appropriate template, fills in the variables, converts newlines to `<br>` for HTML rendering, and sends the fully constructed content to this workflow.

#### Workflow 3: "Update Close Dates, Update CIS, and Send Email" (on PLIC_Date_Changes_2)

**Trigger:** A new response is created on `PLIC_Date_Changes_2` (newly created responses only — not API updates, imported responses, or incomplete responses).

This workflow runs when an instructor submits the date change form. It first validates that at least one survey was selected for changes, then calls the `changePLICDates` Lambda to process the changes, updates the CIS embedded data, and sends an appropriate confirmation email based on which surveys were updated.

```
Instructor submits PLIC_Date_Changes_2 form
(provides ResponseID, new close dates, reminder preferences)
        │
        ▼
┌──────────────────────────────────────────────┐
│  Decision: At least one survey change         │
│  requested?                                   │
│  Q3 "Which survey would you like to change    │
│  the end date for?" Selected Count > 0        │
└──────────────────────────────────────────────┘
        │ (if yes)
        ▼
┌──────────────────────────────────────────────┐
│  T-ID 1: Initiate necessary changes for CIS  │
│  POST → changePLICDates Lambda                │
│  Returns: Email, Instructor name, Course      │
│  info, JSON Request, PRE/POST Update Possible │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│  T-ID 5: Update CIS Response's Embedded Data  │
│  PUT → Qualtrics API                          │
│  Uses JSON Request from T-ID 1                │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│  Decision: Both pre- and post-survey          │
│  changes are requested?                       │
│  (PRE Update Possible == true AND             │
│   POST Update Possible == true)               │
└──────────────────────────────────────────────┘
       ╱ ╲
      ╱   ╲
  Branch 1           Otherwise
  (Both)
     │                    │
     ▼                    ▼
┌───────────┐    ┌──────────────────────────────────────┐
│ T-ID 2:   │    │  Decision: Only pre-survey change     │
│ Email     │    │  is requested and valid?              │
│ (both     │    │  (PRE Update Possible == true)        │
│  dates)   │    └──────────────────────────────────────┘
└───────────┘           ╱ ╲
     │                 ╱   ╲
     ▼             Branch 1     Otherwise
 End of           (Pre only)
 workflow            │              │
                     ▼              ▼
              ┌───────────┐  ┌───────────────────────────────┐
              │ T-ID 3:   │  │  Decision: Only post-survey    │
              │ Email     │  │  change is requested and valid? │
              │ (pre-     │  │  (POST Update Possible == true) │
              │  survey   │  └───────────────────────────────┘
              │  date)    │         │
              └───────────┘     Branch 1
                   │           (Post only)
                   ▼              │
               End of             ▼
               workflow    ┌───────────┐
                           │ T-ID 4:   │
                           │ Email     │
                           │ (post-    │
                           │  survey   │
                           │  date)    │
                           └───────────┘
                                │
                                ▼
                            End of
                            workflow
```

**Task details:**

| Step | Type | Target | What it does |
|------|------|--------|-------------|
| Decision (gate) | Conditional | — | Checks that Q3 ("Which survey would you like to change the end date for?") has at least one selection (`Selected Count > 0`). If nothing is selected, the workflow ends immediately. |
| T-ID 1 | WebService (POST) | `changePLICDates` Lambda | Sends the instructor's Response ID, requested close dates, and reminder preferences. Returns instructor details, a `JSON Request` payload for updating the CIS, and `PRE Update Possible` / `POST Update Possible` flags. |
| T-ID 5 | WebService (PUT) | Qualtrics API (`/API/v3/responses/{ResponseID}`) | Updates the CIS response's embedded data using the `JSON Request` returned by T-ID 1 (contains new close dates, reminder settings, and cleared tracking fields as needed). Always runs regardless of which branch is taken for email. |
| Decision (email routing) | Conditional (3 levels) | — | Cascading check: both updates possible -> T-ID 2; only pre possible -> T-ID 3; only post possible -> T-ID 4; neither -> no email sent. |
| T-ID 2 | Email | Instructor | Sends confirmation email for **both** pre- and post-survey date changes. |
| T-ID 3 | Email | Instructor | Sends confirmation email for **pre-survey only** date change. |
| T-ID 4 | Email | Instructor | Sends confirmation email for **post-survey only** date change. |

**WebService parameters for T-ID 1:**

| Body Field | Value | Source |
|------------|-------|--------|
| `Instructor_ID` | `${q://QID6/ChoiceTextEntryValue}` | Date change form answer (CIS Response ID) |
| `Requested Post-Survey Close Date` | `${q://QID18/ChoiceTextEntryValue}` | Date change form answer |
| `Requested Post-Survey Reminder` | `${q://QID10/ChoiceGroup/SelectedChoices}` | Date change form answer |
| `Requested Pre-Survey Close Date` | `${q://QID19/ChoiceTextEntryValue}` | Date change form answer |
| `Requested Pre-Survey Reminder` | `${q://QID8/ChoiceGroup/SelectedChoices}` | Date change form answer |

**T-ID 1 return values (piped into later tasks):**

| Path | Piped-text label | Description |
|------|------------------|-------------|
| `$.Email` | Email | Instructor email address |
| `$["Course Name"]` | Course Name | From CIS |
| `$["Course Number"]` | Course Number | From CIS |
| `$["Instructor First"]` | Instructor First | From CIS |
| `$["Instructor Last"]` | Instructor Last | From CIS |
| `$["JSON Request"]` | JSON Request | Pre-built embedded data payload for CIS update |
| `$["POST Update Possible"]` | POST Update Possible | `true` or `false` |
| `$["PRE Update Possible"]` | PRE Update Possible | `true` or `false` |

**T-ID 5 JSON body (CIS embedded data update):**

```json
{
  "surveyId": "SV_0jlsamgr7VAmvum",
  "resetRecordedDate": true,
  "embeddedData": {
    ~{ch://OCAC_NFVla3SpDfMXrix/$["JSON Request"]}
  }
}
```

Note: The `JSON Request` value from T-ID 1 is injected directly into the `embeddedData` object. This is the pre-formatted key-value string built by the `changePLICDates` Lambda (e.g., `"Post-Survey Close Date": "2025/12/02", "Report Sent": null, "Post-Survey Reminder": null`).

**T-ID 2 email (both pre- and post-survey changes):**

| Field | Value |
|-------|-------|
| **To** | `~{ch://OCAC_NFVla3SpDfMXrix/$.Email}` (instructor email from T-ID 1) |
| **From** | CPERL@cornell.edu (display name: "Cornell Physics Education Research Lab") |
| **Reply-To** | CPERL@cornell.edu |
| **Subject** | `Changes to PLIC Pre- and Post-Survey Dates (${q://QID6/ChoiceTextEntryValue})` |

> Dear Dr. ~{ch://OCAC_NFVla3SpDfMXrix/$["Instructor First"]} ~{ch://OCAC_NFVla3SpDfMXrix/$["Instructor Last"]},
>
> Thank you again for participating in the PLIC Pre- and Post-survey. Changes were recently made to the close dates for your class, ~{ch://OCAC_NFVla3SpDfMXrix/$["Course Name"]} (~{ch://OCAC_NFVla3SpDfMXrix/$["Course Number"]}). The Pre-survey is currently set to close for students on the following date (yyyy/mm/dd):
>
> ${q://QID19/ChoiceTextEntryValue}
>
> The Post-survey is currently set to close for students on the following date (yyyy/mm/dd):
>
> ${q://QID18/ChoiceTextEntryValue}
>
> If you would like to change this date again, please fill out the form again with your unique ResponseID (${q://QID6/ChoiceTextEntryValue}):
>
> https://cornell.ca1.qualtrics.com/jfe/form/SV_3INpKjeS7Mjss06
>
> Thank you,
> Cornell Physics Education Research Lab
>
> This message was sent by an automated system.

**T-ID 3 email (pre-survey only change):**

| Field | Value |
|-------|-------|
| **To** | `~{ch://OCAC_NFVla3SpDfMXrix/$.Email}` |
| **From** | CPERL@cornell.edu (display name: "Cornell Physics Education Research Lab") |
| **Reply-To** | CPERL@cornell.edu |
| **Subject** | `Changes to PLIC Pre-Survey Dates (${q://QID6/ChoiceTextEntryValue})` |

> Dear Dr. ~{ch://OCAC_NFVla3SpDfMXrix/$["Instructor First"]} ~{ch://OCAC_NFVla3SpDfMXrix/$["Instructor Last"]},
>
> Thank you again for participating in the PLIC Pre-survey. Changes were recently made to the close date for your class, ~{ch://OCAC_NFVla3SpDfMXrix/$["Course Name"]} (~{ch://OCAC_NFVla3SpDfMXrix/$["Course Number"]}). This Pre-survey is currently set to close for students on the following date (yyyy/mm/dd):
>
> ${q://QID19/ChoiceTextEntryValue}
>
> If you would like to change this date again, please fill out the form again with your unique ResponseID (${q://QID6/ChoiceTextEntryValue}):
>
> https://cornell.ca1.qualtrics.com/jfe/form/SV_3INpKjeS7Mjss06
>
> Thank you,
> Cornell Physics Education Research Lab
>
> This message was sent by an automated system.

**T-ID 4 email (post-survey only change):**

| Field | Value |
|-------|-------|
| **To** | `~{ch://OCAC_NFVla3SpDfMXrix/$.Email}` |
| **From** | CPERL@cornell.edu (display name: "Cornell Physics Education Research Lab") |
| **Reply-To** | CPERL@cornell.edu |
| **Subject** | `Changes to PLIC Post-Survey Dates (${q://QID6/ChoiceTextEntryValue})` |

> Dear Dr. ~{ch://OCAC_NFVla3SpDfMXrix/$["Instructor First"]} ~{ch://OCAC_NFVla3SpDfMXrix/$["Instructor Last"]},
>
> Thank you again for participating in the PLIC Post-survey. Changes were recently made to the close date for your class, ~{ch://OCAC_NFVla3SpDfMXrix/$["Course Name"]} (~{ch://OCAC_NFVla3SpDfMXrix/$["Course Number"]}). This Post-survey is currently set to close for students on the following date (yyyy/mm/dd):
>
> ${q://QID18/ChoiceTextEntryValue}
>
> If you would like to change this date again, please fill out the form again with your unique ResponseID (${q://QID6/ChoiceTextEntryValue}):
>
> https://cornell.ca1.qualtrics.com/jfe/form/SV_3INpKjeS7Mjss06
>
> Thank you,
> Cornell Physics Education Research Lab
>
> This message was sent by an automated system.

---

## Email Templates

All email templates are in `automatePLIC/utilities/` and use Python string formatting with the following variables:

| Variable | Source |
|----------|--------|
| `{first_name}` | CIS field `QID2_TEXT` |
| `{last_name}` | CIS field `QID59_TEXT` |
| `{survey_type}` | Always `"PLIC"` |
| `{survey_condition}` | `"Pre"` or `"Post"` |
| `{course_name}` | CIS field `QID9_TEXT` |
| `{course_number}` | CIS field `QID10_TEXT` |
| `{close_date}` | Pre- or Post-Survey Close Date |
| `{open_date}` | Post-survey close date minus 14 days |
| `{survey_url}` | `{QUALTRICS_BASE_URL}/jfe/form/{SurveyID}` |
| `{response_count}` | Auditable response count from Qualtrics |
| `{course_identifier}` | Class ID (CIS response ID) |
| `{change_url}` | Date change form URL |
| `{dashboard_url}` | `plicdashboard.streamlit.app/?class_id={class_id}` |
| `{survey_admin}` | `"Cornell Physics Education Research Lab"` |

### Template summary:

| Template | When sent | Key content |
|----------|-----------|-------------|
| `memo.txt` | 16 days before post-survey close | Informs instructor of upcoming post-survey date |
| `survey_sent.txt` | 14 days before post-survey close | Provides post-survey link, asks to share with students |
| `reminder.txt` | 4 days before close (pre or post) | Reminder with current response count |
| `survey_closed.txt` | When pre-survey closes | Notifies pre-survey is closed, mentions upcoming post-survey |
| `report_sent.txt` | When post-survey closes | Provides dashboard link and class identifier for data access |

---

## Environment Variables — Complete Reference

| Variable | Used By | Description |
|----------|---------|-------------|
| `QUALTRICS_API_TOKEN` | All except update_inprogress | Qualtrics API authentication token |
| `QUALTRICS_BASE_URL` | All except update_inprogress | Qualtrics datacenter URL (e.g., `https://cornell.ca1.qualtrics.com`) |
| `CIS_SURVEY_ID` | All | Course Information Survey ID in Qualtrics |
| `EXPECTED_TOKEN` | All | Shared API key for request authentication |
| `INPROGRESS_BUCKET_NAME` | automatePLIC, changePLICDates, update_inprogress | S3 bucket for in-progress tracking |
| `INPROGRESS_FILE_NAME` | automatePLIC, changePLICDates, update_inprogress, uploadDashboardData | Filename of the tracking CSV |
| `DASHBOARD_BUCKET_NAME` | uploadDashboardData | S3 bucket for processed dashboard data |
| `DASHBOARD_KEY` | uploadDashboardData | Base key for dashboard CSV files |
| `EMAIL_REQUEST_URL` | automatePLIC | Qualtrics Workflow trigger URL for email sending |

---

## Deployment Notes

- Each Lambda function is deployed as a self-contained package that includes its source code and all Python dependencies (notably `requests`, `boto3`, `urllib3`, `certifi`, and for `uploadDashboardData`: `pandas`, `numpy`) bundled in the deployment ZIP.
- The `plicsurvey.qsf` template file for `createPLICSurvey` is included in the deployment package alongside the handler.
- The question weights CSV and column ordering CSV for `uploadDashboardData` are bundled inside the `utilities/` directory.
- `automatePLIC` must have an EventBridge (CloudWatch Events) rule configured as its trigger to run on a recurring schedule (frequent enough to handle one action per invocation across all active surveys).
- The four API-triggered functions (`createPLICSurvey`, `changePLICDates`, `update_inprogress`, `uploadDashboardData`) should each have an API Gateway trigger configured.
- Lambda execution roles need:
  - `s3:GetObject` and `s3:PutObject` permissions on the in-progress and dashboard buckets.
  - Outbound HTTPS access to Qualtrics APIs and the `uploadDashboardData` API Gateway endpoint.
- The `uploadDashboardData` function requires a longer timeout and more memory than the others due to pandas/numpy data processing.

---

## Typical Survey Lifecycle

```
1. Instructor fills out CIS in Qualtrics
                │
2. createPLICSurvey (x2) ──► Pre-survey and Post-survey created + activated
                │
3. update_inprogress ──► Class added to in-progress tracking
                │
4. Instructor receives email with pre-survey link
                │
5. Instructor distributes pre-survey link to students
                │
6. Students complete the pre-survey
                │
    ┌───────────────────────────────────────────────┐
    │  automatePLIC (scheduled, recurring)           │
    │                                                │
    │  PRE-SURVEY PHASE:                             │
    │  • Sends reminder if close date ≤ 4 days       │
    │  • Closes pre-survey when date passes          │
    │  • Sends "survey closed" email                 │
    │                                                │
    │  POST-SURVEY PHASE:                            │
    │  • Sends memo 16 days before close             │
    │  • Sends post-survey link 14 days before close │
    │  • Sends reminder if close date ≤ 4 days       │
    │  • Closes post-survey when date passes         │
    │  • Triggers data upload on close               │
    └───────────────────────────────────────────────┘
                │
7. uploadDashboardData ──► Scores pre+post, matches students, uploads to S3
                │
8. Streamlit dashboard reads from S3 and displays results
```

If an instructor needs to reopen or extend a survey, they use the **date change form**, which triggers **changePLICDates**. This reactivates the survey, sets a new close date, clears tracking fields, and re-adds the class to in-progress tracking so `automatePLIC` picks it up again.

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| Survey not being monitored by automation | Class ID missing from in-progress CSV | Call `update_inprogress` to add it |
| Reminder emails not sending | Reminder field already has a date value in CIS response, or close date is more than 4 days away | Use `changePLICDates` to reset reminder preference |
| Survey not closing automatically | Class ID not in in-progress CSV, or `automatePLIC` schedule is paused | Verify EventBridge rule is active and class is tracked |
| Post-survey link not being sent | `Post-Survey Sent` field already has a date, or close date is more than 14 days away | Check CIS embedded data; use `changePLICDates` to reset if needed |
| Dashboard data not appearing | `uploadDashboardData` failed or hasn't run yet | Check Lambda CloudWatch logs; may need to invoke manually |
| Duplicate data in dashboard | Survey was reopened and re-closed | The upload function handles this by removing existing rows with the same Class_ID before appending |
| Pre/post student matching is poor | Students used different names or IDs on pre vs. post surveys | Matching uses full name, reversed name, and student ID — unmatched responses are still included |
| 403 errors on API calls | `EXPECTED_TOKEN` mismatch between caller and Lambda | Verify environment variables match across all functions |
| Qualtrics API errors | Token expired or rate-limited | Verify `QUALTRICS_API_TOKEN` is current; check Qualtrics API limits |
| `automatePLIC` not processing all surveys | By design, it processes one action per invocation | Ensure the EventBridge schedule runs frequently enough (e.g., every few minutes) |
| Date change form not working | Instructor used wrong Response ID, or survey ID is missing from CIS | Verify the CIS response has the expected Survey ID fields populated |

---

## File Structure

```
automatePLIC/
|-- lambda_function.py          (main orchestrator)
|-- utilities/
|   |-- qualtrics_utils.py      (API calls for surveys)
|   |-- email_utils.py          (email building & sending)
|   |-- memo.txt                (email template)
|   |-- survey_sent.txt         (email template)
|   |-- reminder.txt            (email template)
|   |-- survey_closed.txt       (email template)
|   +-- report_sent.txt         (email template)
+-- [requests, certifi, urllib3, charset_normalizer bundles]

changePLICDates/
|-- lambda_function.py          (HTTP endpoint for date changes)
+-- [requests library bundles]

createPLICSurvey/
|-- lambda_function.py          (survey creation)
|-- plicsurvey.qsf              (QSF template)
+-- [requests library bundles]

update_inprogress/
+-- lambda_function.py          (CSV utility)

uploadDashboardData/
|-- lambda_function.py          (main handler)
|-- utilities/
|   |-- compiling_utils.py      (orchestrator)
|   |-- qualtrics_utils.py      (API & exports)
|   |-- processing_utils.py     (name/response matching)
|   |-- scoring_utils.py        (PLIC scoring)
|   |-- ColumnOrdering_June2025.csv  (column order spec)
|   +-- QuestionText_June2025.csv    (scoring weights)
+-- [requests, pandas, numpy bundles]
```

---

## Acknowledgements

Current dashboard built by Matthew Dew. Previous iteration developed by Cole Walsh. Original PLIC server based on work by Wilcox, Zwickl, Hobbs, Aiken, Welch, & Lewandowski (2016).
