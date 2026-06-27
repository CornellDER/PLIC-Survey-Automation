# changePLICDates Lambda function
import json
import boto3
import requests
import os
import io
from datetime import datetime
import csv

s3 = boto3.client('s3')

# ENV VARS: set in Lambda config
QUALTRICS_API_TOKEN = os.environ['QUALTRICS_API_TOKEN']
QUALTRICS_BASE_URL = os.environ['QUALTRICS_BASE_URL']
EXPECTED_TOKEN = os.environ['EXPECTED_TOKEN']
CIS_SURVEY_ID = os.environ['CIS_SURVEY_ID']
BUCKET_NAME = os.environ['INPROGRESS_BUCKET_NAME']
CSV_KEY = os.environ['INPROGRESS_FILE_NAME']

def update_csv_add_row(bucket_name, key, class_id):
    """
    Downloads a CSV from S3, adds a row with "Class_ID" = class_id,
    and uploads the updated CSV back to S3.
    """
    try:
        # Download CSV from S3
        response = s3.get_object(Bucket=bucket_name, Key=key)
        csv_data = response['Body'].read().decode('utf-8')
        csv_lines = csv_data.splitlines()

        # Read CSV into list of dicts
        reader = csv.DictReader(csv_lines)
        rows = list(reader)

        # Get fieldnames (columns) from original CSV
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError("CSV has no header row")

        print("CSV headers:", fieldnames)  # Debug print
        # Remove BOM if present in first header
        if fieldnames[0].startswith('\ufeff'):
            fieldnames[0] = fieldnames[0].replace('\ufeff', '')
        print("CSV headers after BOM removal:", fieldnames)

        # Fix keys in existing rows to remove BOM from keys
        cleaned_rows = []
        for row in rows:
            new_row = {}
            for k, v in row.items():
                new_key = k.replace('\ufeff', '')
                new_row[new_key] = v
            cleaned_rows.append(new_row)
        rows = cleaned_rows

        # Append new row with "Class_ID" = class_id
        new_row = {field: "" for field in fieldnames}
        new_row["Class_ID"] = class_id
        rows.append(new_row)

        # Write updated CSV to a string buffer
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

        updated_csv_data = output.getvalue()

        # Upload updated CSV back to S3
        s3.put_object(Bucket=bucket_name, Key=key, Body=updated_csv_data.encode('utf-8'))

        print("Added new row and updated CSV in S3 successfully.")

    except Exception as e:
        print(f"Error updating CSV in S3: {e}")

def activate_survey(survey_id, headers):
    # Activate the survey
    activate_url = f"{QUALTRICS_BASE_URL}/API/v3/surveys/{survey_id}"
    activate_payload = {
        "isActive": True
    }
    activate_response = requests.put(activate_url, headers=headers, json=activate_payload)
    activate_response.raise_for_status()

def lambda_handler(event, context):
    try:
        # Extract token from headers
        token = event.get("headers", {}).get("x-api-key")

        if token != EXPECTED_TOKEN:
            return {
                "statusCode": 403,
                "body": json.dumps({"message": "Forbidden: Invalid token"})
            }

        # Parse body
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event.get("body", {})

        instructor_id = body.get("Instructor_ID")
        requested_post_closedate = body.get("Requested Post-Survey Close Date")
        requested_post_reminder = body.get("Requested Post-Survey Reminder")
        requested_pre_closedate = body.get("Requested Pre-Survey Close Date")
        requested_pre_reminder = body.get("Requested Pre-Survey Reminder")

        if not instructor_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Instructor_ID is required"})
            }

        # Get response from the CIS survey
        export_url = f"{QUALTRICS_BASE_URL}/API/v3/surveys/{CIS_SURVEY_ID}/responses/{instructor_id}"
        headers = {
            "X-API-TOKEN": QUALTRICS_API_TOKEN,
            "Content-Type": "application/json"
        }
        response = requests.get(export_url, headers=headers)

        if response.status_code == 404:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Response not found for given Instructor_ID"})
            }

        response.raise_for_status()
        response_data = response.json()

        # Extract data from CIS response
        values = response_data.get("result", {}).get("values", {})
        instructor_email = values.get("QID3_TEXT")
        post_id = values.get("Post-Survey ID")
        post_reminder = values.get("Post-Survey Reminder")
        post_closed = values.get("Post-Survey Closed")
        pre_id = values.get("Pre-Survey ID")
        pre_reminder = values.get("Pre-Survey Reminder")
        pre_closed = values.get("Pre-Survey Closed")

        instructor_first = values.get("QID2_TEXT")
        instructor_last = values.get("QID59_TEXT")
        course_name = values.get("QID9_TEXT")
        course_number = values.get("QID10_TEXT")

        # Initialize change status for emailing on Qualtrics
        pre_update_possible = False
        post_update_possible = False

        # Initialize response_body
        response_body = {}

        # Handle pre-survey changes (if appropriate)
        if requested_pre_closedate not in (None, "") and pre_id not in (None, ""):
            response_body["Pre-Survey Close Date"] = requested_pre_closedate
            pre_update_possible = True
            if pre_closed is not None:
                activate_survey(pre_id, headers)

                # Add to InProgress.csv
                update_csv_add_row(bucket_name=BUCKET_NAME, key=CSV_KEY, class_id = instructor_id)

                response_body["Pre-Survey Closed"] = None
                response_body["Report Sent"] = None
            if requested_pre_reminder == "Yes":
                response_body["Pre-Survey Reminder"] = None
            elif requested_pre_reminder == "No" and pre_reminder is None:
                response_body["Pre-Survey Reminder"] = datetime.today().strftime("%Y/%m/%d")

        # Handle post-survey changes (if appropriate)
        if requested_post_closedate not in (None, "") and post_id not in (None, ""):
            response_body["Post-Survey Close Date"] = requested_post_closedate
            post_update_possible = True
            if post_closed is not None:
                activate_survey(post_id, headers)
                # Add to InProgress.csv
                update_csv_add_row(bucket_name=BUCKET_NAME, key=CSV_KEY, class_id = instructor_id)

                response_body["Post-Survey Closed"] = None
                response_body["Report Sent"] = None
            if requested_post_reminder == "Yes":
                response_body["Post-Survey Reminder"] = None
            elif requested_post_reminder == "No" and post_reminder is None:
                response_body["Post-Survey Reminder"] = datetime.today().strftime("%Y/%m/%d")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "Email": instructor_email,
                "PRE Update Possible": pre_update_possible,
                "POST Update Possible": post_update_possible,
                "Instructor First": instructor_first,
                "Instructor Last": instructor_last,
                "Course Name": course_name,
                "Course Number": course_number,
                "JSON Request": json.dumps(response_body)[1:-1] #builds JSON request for Workflows use
            })
        }


    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
