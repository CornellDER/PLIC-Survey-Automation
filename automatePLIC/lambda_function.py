# automatePLIC Lambda function
import boto3
import json
import os
import csv
import io
import requests
import datetime
from zoneinfo import ZoneInfo

from utilities.email_utils import send_email
from utilities.qualtrics_utils import update_response_data, get_response_data, close_survey

s3 = boto3.client('s3')

# ENV VARS: set in Lambda config
BUCKET_NAME = os.environ['INPROGRESS_BUCKET_NAME']
CSV_KEY = os.environ['INPROGRESS_FILE_NAME']
EXPECTED_TOKEN = os.environ['EXPECTED_TOKEN']

def call_upload_dashboard_data(instructor_id):
    """
    Calls the uploadDashboardData API endpoint using the instructor ID.
    """
    # API Gateway URL
    api_url = 'https://ao2r2skkh2.execute-api.us-east-2.amazonaws.com/default/uploadDashboardData'

    # Headers
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': EXPECTED_TOKEN
    }

    # JSON body payload
    payload = {
        "Instructor_ID": instructor_id
    }

    # Make the POST request
    response = requests.post(api_url, headers=headers, data=json.dumps(payload))

    # Check response
    if response.status_code == 200:
        print("Success!")
        print("Response JSON:", response.json())
    else:
        print(f"Failed to call API. Status code: {response.status_code}")
        print("Response text:", response.text)

    return {
        'statusCode': response.status_code,
        'body': response.text
    }

def obtain_inprogress():
    """
    Returns a list of the class IDs for courses that are currently in progress.

    Raises:
        KeyError: if 'Class_ID' column is missing.
        Exception: for any other issues during S3 access or CSV parsing.
    """
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=CSV_KEY)
    except s3.exceptions.NoSuchKey:
        raise FileNotFoundError(f"The file '{CSV_KEY}' does not exist in bucket '{BUCKET_NAME}'.")
    except Exception as e:
        raise Exception(f"Failed to fetch file from S3: {str(e)}")

    try:
        content = response['Body'].read().decode('utf-8')
        csvfile = io.StringIO(content)
        reader = csv.DictReader(csvfile)

        if 'Class_ID' not in reader.fieldnames:
            raise KeyError("Missing 'Class_ID' column in CSV.")

        class_ids = [row['Class_ID'] for row in reader if row['Class_ID'].strip()]
        return class_ids

    except Exception as e:
        raise Exception(f"Failed to parse CSV file: {str(e)}")

def lambda_handler(event, context):
    """
    This function builds a JSON request that will change all necessary variables. 
    Note: this function only takes one action at a time. This is to ensure the 
    function runtime remains low and interfaces well with Qualtrics.
    This is done using the break statements. This is compensated for by 
    calling the function more frequently. 
    """
    try:
        # Obtain all the class IDs for courses that are unfinished.
        active_ids = obtain_inprogress()

        # Iterate through each active class ID. 
        for class_id in active_ids:
            # Get the response data from Qualtrics
            values = get_response_data(class_id)
            # Determine what change needs to be made
            pre_id = values.get("Pre-Survey ID")
            post_close_date = values.get("Post-Survey Close Date")
            pre_close_date = values.get("Pre-Survey Close Date")
            post_reminder = values.get("Post-Survey Reminder")
            pre_reminder = values.get("Pre-Survey Reminder")
            post_id = values.get("Post-Survey ID")
            post_memo = values.get("Post-Survey Memo")
            post_closed = values.get("Post-Survey Closed")
            pre_closed = values.get("Pre-Survey Closed")
            post_sent = values.get("Post-Survey Sent")

            # Get current date in Eastern time for comparisons
            current_date = datetime.datetime.now(tz=ZoneInfo("America/New_York")).date()
            
            # Format dates for comparisons
            if pre_close_date not in (None, ""):
                pre_close_date = datetime.datetime.strptime(pre_close_date, "%Y/%m/%d").date()
            else:
                pre_close_date = None

            if post_close_date not in (None, ""):
                post_close_date = datetime.datetime.strptime(post_close_date, "%Y/%m/%d").date()
            else:
                post_close_date = None  # or assign a default date if that makes sense
            
            # Update appropriate cells to the current date
            # First, iterate through pre-survey requests if applicable (i.e. pre_id exists)
            if pre_id not in (None, ""):
                if pre_close_date <= current_date and pre_closed in (None, ""):
                    # Close the pre-survey
                    close_survey(pre_id)
                    # Email pre-survey closed
                    send_email(class_id = class_id, reponse_data_values = values, pre_or_post = "Pre", email_template = "survey_closed")
                    
                    print(pre_reminder)
                    print(pre_reminder is None)
                    print(pre_reminder in (None, ""))

                    # If we need to close the pre-survey now but haven't done earlier tasks, set those as well
                    embedded_update_variables = ['Pre-Survey Closed']
                    if pre_reminder in (None, ""):
                        print("Post reminder detected as None or empty!")
                        embedded_update_variables.append("Pre-Survey Reminder")

                    # Update CIS "Pre-Survey Closed" (and other variables if needed) to current date
                    update_response_data(class_id, embedded_update_variables)

                    # Finish this function call
                    break
                elif (pre_close_date - current_date).days <= 4 and pre_reminder in (None, ""):
                    # Email pre-survey reminder
                    send_email(class_id = class_id, reponse_data_values = values, pre_or_post = "Pre", email_template = "reminder")
                    # Change CIS "Pre-Survey Reminder" to current date
                    update_response_data(class_id, ["Pre-Survey Reminder"])

                    # Finish this function call
                    break
            # Next, iterate through post-survey requests
            if post_close_date <= current_date and post_closed in (None, ""):
                # Close the post-survey
                close_survey(post_id)
                # Call upload dashboard data using a function
                call_upload_dashboard_data(class_id)

                # Email report sent
                send_email(class_id = class_id, reponse_data_values = values, pre_or_post = "Post", email_template = "report_sent")
                
                # If we need to close the post-survey now but haven't done earlier tasks, set those as well
                embedded_update_variables = ['Post-Survey Closed', 'Report Sent']
                # Build necessary updates
                if post_reminder in (None, ""):
                    embedded_update_variables.append('Post-Survey Reminder')
                if post_sent in (None, ""):
                    embedded_update_variables.append('Post-Survey Sent')
                if post_memo in (None, ""):
                    embedded_update_variables.append("Post-Survey Memo")
                # Change CIS "Post-Survey Closed" (and other variables if needed) to current date
                update_response_data(class_id, embedded_update_variables)

                # Finish this function call
                break

            elif (post_close_date - current_date).days <= 4 and post_reminder in (None, ""):
                # Email post-survey reminder
                send_email(class_id = class_id, reponse_data_values = values, pre_or_post = "Post", email_template = "reminder")
                
                # If we need to send the post-survey reminder now but haven't done earlier tasks, set those as well
                embedded_update_variables = ['Post-Survey Reminder']
                # Build necessary updates
                if post_sent in (None, ""):
                    embedded_update_variables.append('Post-Survey Sent')
                if post_memo in (None, ""):
                    embedded_update_variables.append("Post-Survey Memo")
                # Change CIS "Post-Survey Reminder" (and other variables if needed) to current date
                update_response_data(class_id, embedded_update_variables)

                # Finish this function call
                break

            elif (post_close_date - current_date).days <= 14 and post_sent in (None, ""):
                # Email post-survey sent
                send_email(class_id = class_id, reponse_data_values = values, pre_or_post = "Post", email_template = "survey_sent")
                
                # If we need to send the post-survey now but haven't sent the memo, set that as well
                embedded_update_variables = ['Post-Survey Sent']
                # Build necessary update
                if post_memo in (None, ""):
                    embedded_update_variables.append("Post-Survey Memo")
                # Change CIS "Post-Survey Sent" (and other variables if needed) to current date
                update_response_data(class_id, embedded_update_variables)

                # Finish this function call
                break

            elif (post_close_date - current_date).days <= 16 and post_memo in (None, ""):
                # Email post-survey memo 
                send_email(class_id = class_id, reponse_data_values = values, pre_or_post = "Post", email_template = "memo")
                # Change CIS "Post-Survey Memo" to current date
                update_response_data(class_id, ["Post-Survey Memo"])

                # Finish this function call
                break

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Success",
                "active_ids": active_ids
            })
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Error",
                "details": str(e)
            })
        }