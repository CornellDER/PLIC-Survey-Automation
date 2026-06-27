from datetime import datetime
import requests
import json
import os

QUALTRICS_API_TOKEN = os.environ['QUALTRICS_API_TOKEN']
QUALTRICS_BASE_URL = os.environ['QUALTRICS_BASE_URL']
CIS_SURVEY_ID = os.environ['CIS_SURVEY_ID']

def get_response_count(survey_id):
    '''
    This function obtains the number of "auditable" response counts for a given survey ID. 
    '''

    # Build the JSON request
    base_url = f'{QUALTRICS_BASE_URL}/API/v3/surveys/{survey_id}'
    headers = {
        'Content-Type': 'application/json',
        'X-API-TOKEN': QUALTRICS_API_TOKEN
    }

    # Make the JSON request
    response = requests.get(base_url, headers=headers)

    # This obtains the number of "auditable" responses
    data = response.json()
    response_counts = data.get('result', {}).get('responseCounts', {})
    response_count = response_counts.get('auditable', 0)

    return response_count


def get_response_data(class_id):
    '''
    Obtains data for an instructor's response on the course information survey. 
    '''

    # Get response from the CIS survey
    export_url = f"{QUALTRICS_BASE_URL}/API/v3/surveys/{CIS_SURVEY_ID}/responses/{class_id}"
    headers = {
        "X-API-TOKEN": QUALTRICS_API_TOKEN,
        "Content-Type": "application/json"
    }
    response = requests.get(export_url, headers=headers)

    if response.status_code == 404:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Response not found for given Class_ID"})
        }

    response.raise_for_status()
    response_data = response.json()

    # Extract data from CIS response
    values = response_data.get("result", {}).get("values", {})

    return values

def update_response_data(response_id, embedded_variables):
    '''
    Updates embedded data for a survey respondent for a list of given fields to the current date.
    '''
    # URL for the PUT request
    url = f"{QUALTRICS_BASE_URL}/API/v3/responses/{response_id}"

    # Headers
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-TOKEN": QUALTRICS_API_TOKEN
    }

    # Current date as string
    current_date = datetime.today().strftime("%Y/%m/%d")

    # Build embeddedData dictionary
    embedded_data = {var: current_date for var in embedded_variables}

    # JSON payload
    payload = {
        "surveyId": CIS_SURVEY_ID,
        "resetRecordedDate": True,
        "embeddedData": embedded_data
    }

    # Make the PUT request
    response = requests.put(url, headers=headers, data=json.dumps(payload))

    # Check the response
    if response.status_code == 200:
        print("Successfully updated embedded data.")
    else:
        print(f"Failed to update. Status code: {response.status_code}")
        print(response.text)

def close_survey(survey_id):
    '''
    This function closes a survey given the survey's ID. 
    '''
    # Deactivate the survey
    deactivate_url = f"{QUALTRICS_BASE_URL}/API/v3/surveys/{survey_id}"
    headers = {
        "X-API-TOKEN": QUALTRICS_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "isActive": False
    }

    response = requests.put(deactivate_url, headers=headers, json=payload)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to close survey: {response.status_code}, {response.text}")