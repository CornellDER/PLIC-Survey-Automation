import requests
import zipfile
import io
import pandas as pd
import os

global CIS_SURVEY_ID, QUALTRICS_API_TOKEN, QUALTRICS_BASE_URL

# Load environment variables
CIS_SURVEY_ID = os.environ['CIS_SURVEY_ID']
QUALTRICS_API_TOKEN = os.environ['QUALTRICS_API_TOKEN']
QUALTRICS_BASE_URL = os.environ['QUALTRICS_BASE_URL']

def get_cis_response_data(instructor_id):
    """
    Retrieve survey response data from the CIS survey in Qualtrics using the response ID.

    Parameters:
        instructor_id (str): The Qualtrics response ID (used here as the Instructor_ID).

    Returns:
        dict: A dictionary containing post_id, pre_id, course_type, and class_size.
              If an error occurs, the dictionary will contain an 'error' key with the message.
    """
    try:
        # Build the API request URL using global variables
        export_url = f"{QUALTRICS_BASE_URL}/API/v3/surveys/{CIS_SURVEY_ID}/responses/{instructor_id}"
        
        # Set up the request headers with API token
        headers = {
            "X-API-TOKEN": QUALTRICS_API_TOKEN,
            "Content-Type": "application/json"
        }

        # Make the API GET request
        response = requests.get(export_url, headers=headers)

        # Handle not found error (invalid response ID)
        if response.status_code == 404:
            return {"error": "Response not found for the given Instructor_ID"}

        # Raise an exception for other HTTP errors
        response.raise_for_status()

        # Parse the JSON response
        response_data = response.json()

        # Safely extract values from the response
        values = response_data.get("result", {}).get("values", {})
        post_id = values.get("Post-Survey ID")
        pre_id = values.get("Pre-Survey ID")
        course_type = values.get("QID11")
        class_size = values.get("QID12_TEXT")

        # Return extracted values
        return {
            "post_id": post_id,
            "pre_id": pre_id,
            "course_type": course_type,
            "class_size": class_size
        }

    except requests.exceptions.HTTPError as http_err:
        # Handle HTTP errors (other than 404)
        return {"error": f"HTTP error occurred: {http_err}"}

    except requests.exceptions.RequestException as req_err:
        # Handle other requests-related errors
        return {"error": f"Request error occurred: {req_err}"}

    except Exception as e:
        # Handle any other unexpected errors
        return {"error": f"An unexpected error occurred: {e}"}

def download_responses_as_df(survey_id):
    """Download Qualtrics survey responses as a pandas DataFrame without saving to disk."""

    FileFormat = "csv"
    headers = {
        "content-type": "application/json",
        "x-api-token": QUALTRICS_API_TOKEN,
    }

    # Step 1: Create Data Export Request
    downloadRequestUrl = QUALTRICS_BASE_URL + "/API/v3/responseexports/"
    downloadRequestPayload = '{"format":"' + FileFormat + '","surveyId":"' + survey_id + '"}'
    downloadRequestResponse = requests.post(downloadRequestUrl, data=downloadRequestPayload, headers=headers)
    downloadRequestResponse.raise_for_status()
    progressId = downloadRequestResponse.json()["result"]["id"]

    # Step 2: Poll export progress until 100%
    percentComplete = 0
    requestCheckUrl = QUALTRICS_BASE_URL + "/API/v3/responseexports/" + progressId
    while percentComplete < 100:
        requestCheckResponse = requests.get(requestCheckUrl, headers=headers)
        requestCheckResponse.raise_for_status()
        percentComplete = requestCheckResponse.json()["result"]["percentComplete"]

    # Step 3: Download ZIP file content into memory
    requestDownloadUrl = requestCheckUrl + "/file"
    requestDownload = requests.get(requestDownloadUrl, headers=headers, stream=True)
    requestDownload.raise_for_status()

    # Step 4: Load ZIP file from bytes into memory
    zipfile_in_memory = zipfile.ZipFile(io.BytesIO(requestDownload.content))

    # Step 5: Find the CSV filename inside the ZIP (usually there’s one file)
    csv_filename = zipfile_in_memory.namelist()[0]

    # Step 6: Read the CSV directly into a pandas DataFrame
    with zipfile_in_memory.open(csv_filename) as csvfile:
        df = pd.read_csv(csvfile, skiprows=[1,2])

    return df