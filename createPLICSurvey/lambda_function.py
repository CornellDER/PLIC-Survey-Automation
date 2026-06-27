# createPLICSurvey Lambda function
import json
import requests
import os
from datetime import datetime
import re
import unicodedata

# ENV VARS: set in Lambda config
QUALTRICS_API_TOKEN = os.environ['QUALTRICS_API_TOKEN']
QUALTRICS_BASE_URL = os.environ['QUALTRICS_BASE_URL']
EXPECTED_TOKEN = os.environ['EXPECTED_TOKEN']
CIS_SURVEY_ID = os.environ['CIS_SURVEY_ID']

def sanitize_title_field(s, max_length, default="Unknown"):
    '''
    This function cleans text for the survey titles in case an invalid input was given.
    '''
    # Normalize Unicode to ASCII (remove accents, foreign chars beome closest base char)
    s_normalized = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    
    # Replace spaces with underscores
    s_no_spaces = re.sub(r'\s+', '_', s_normalized)

    # Keep only alphanumeric and underscores
    s_clean = re.sub(r'[^A-Za-z0-9_]', '', s_no_spaces)

    # Truncate to max length
    s_clean = s_clean[:max_length]
    return s_clean if s_clean else default

def lambda_handler(event, context):
    try:
        # Extract token from headers
        token = event.get("headers", {}).get("x-api-key")

        if token != EXPECTED_TOKEN:
            return {
                "statusCode": 403,
                "body": json.dumps({"message": "Forbidden: Invalid token"})
            }

        # Proceed with normal processing
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event.get("body", {})
        
        # Extract and build the survey name from provided fields
        semester = body.get("Semester", "")
        year = str(datetime.now().year)  # Automatically set to current year
        institution = body.get("Institution", "")
        number = body.get("Number", "")
        instructor_last = body.get("InstructorLast", "")
        survey_type = body.get("SurveyType", "")
        instructor_id = body.get("Instructor_ID", "")

        # Clean strings for survey title
        institution = sanitize_title_field(institution, 50)
        number = sanitize_title_field(number, 15)
        instructor_last = sanitize_title_field(instructor_last, 50)

        title = f"{semester}{year}_{institution}_{number}_{instructor_last}_{survey_type}_{instructor_id}"

        # Get QSF file
        qsf_path = os.path.join(os.path.dirname(__file__), "plicsurvey.qsf")
        with open(qsf_path, "r") as f:
            qsf_json = json.load(f)

        # Set the survey name inside the QSF before upload
        if "SurveyEntry" in qsf_json:
            qsf_json["SurveyEntry"]["SurveyName"] = title

        # Create survey from QSF
        create_url = f"{QUALTRICS_BASE_URL}/API/v3/survey-definitions"
        headers = {
            "X-API-TOKEN": QUALTRICS_API_TOKEN,
            "Content-Type": "application/json"
        }
        response = requests.post(create_url, headers=headers, json=qsf_json)
        
        # Log the full response for debugging
        print("Response from Qualtrics (Create Survey):", response.text)
        
        response.raise_for_status()

        # Check the response structure
        if 'result' in response.json() and 'SurveyID' in response.json()['result']:
            survey_id = response.json()["result"]["SurveyID"]
        else:
            raise ValueError("Survey ID not found in the response.")

        # Activate the survey
        activate_url = f"{QUALTRICS_BASE_URL}/API/v3/surveys/{survey_id}"
        activate_payload = {
            "isActive": True
        }
        activate_response = requests.put(activate_url, headers=headers, json=activate_payload)
        activate_response.raise_for_status()

        # Build a survey link
        survey_link = f"{QUALTRICS_BASE_URL}/jfe/form/{survey_id}"

        return {
            "statusCode": 200,
            "body": json.dumps({ "surveyId": survey_id, "surveyLink": survey_link })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({ "error": str(e) })
        }
