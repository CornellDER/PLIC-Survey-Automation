import boto3
import json
import os
import io
import pandas as pd
import datetime
from botocore.exceptions import ClientError

from utilities.compiling_utils import compile_course_data

s3 = boto3.client('s3')

BUCKET_NAME = os.environ['DASHBOARD_BUCKET_NAME']
TARGET_KEY = os.environ['DASHBOARD_KEY']
INPROGRESS_KEY = os.environ['INPROGRESS_FILE_NAME']
EXPECTED_TOKEN = os.environ['EXPECTED_TOKEN']

def upload_dataframe(df):
    """
    Uploads the dataframe to the S3 bucket by appending it to an existing CSV 
    named TARGET_KEY_<year>.csv. If the file does not exist, it creates a new one.
    """
    # Get the current year
    current_year = datetime.datetime.now().year
    # Build the dynamic filename/key
    dynamic_key = f"{TARGET_KEY}_{current_year}.csv"
    print(dynamic_key)

    try:
        # Try to read the existing CSV from S3
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=dynamic_key)
        print(obj)
        existing_df = pd.read_csv(obj['Body'])
        print(existing_df)

        # Remove any existing rows with the same Class_ID
        # We do this in case someone re-opens their survey (data should not be duplicated)
        class_id_to_remove = df["Class_ID"].iloc[0]  # get the unique Class_ID
        existing_df = existing_df[existing_df["Class_ID"] != class_id_to_remove]

        # Append new data
        combined_df = pd.concat([existing_df, df], ignore_index=True)

    except ClientError as e:
        # If the file does not exist, start with new dataframe
        if e.response['Error']['Code'] == 'NoSuchKey':
            combined_df = df
        else:
            # If another error occurs, raise it
            raise Exception(f"Error accessing existing CSV: {str(e)}")

    # Convert dataframe to CSV string
    csv_buffer = combined_df.to_csv(index=False)

    # Upload the combined CSV back to S3
    s3.put_object(Bucket=BUCKET_NAME, Key=dynamic_key, Body=csv_buffer)

def update_csv_remove_row(bucket_name, key, class_id):
    """
    Downloads a CSV from S3, removes the row where 'Class_ID' matches class_id,
    and uploads the updated CSV back to S3.
    """
    try:
        # Download CSV from S3
        response = s3.get_object(Bucket=bucket_name, Key=key)
        csv_data = response['Body'].read().decode('utf-8')

        # Read CSV into pandas DataFrame
        df = pd.read_csv(io.StringIO(csv_data))

        # Remove BOM if present in first column name
        first_col = df.columns[0]
        if first_col.startswith('\ufeff'):
            df.rename(columns={first_col: first_col.replace('\ufeff', '')}, inplace=True)

        # Remove row(s) where Class_ID matches input class_id
        updated_df = df[df['Class_ID'].astype(str) != str(class_id)]

        # Write updated DataFrame to CSV in memory
        output = io.StringIO()
        updated_df.to_csv(output, index=False)

        updated_csv_data = output.getvalue()

        # Upload updated CSV back to S3
        s3.put_object(Bucket=bucket_name, Key=key, Body=updated_csv_data.encode('utf-8'))

    except Exception as e:
        print(f"Error updating CSV in S3: {e}")


def lambda_handler(event, context):
    try:
        # Extract token from headers
        token = event.get("headers", {}).get("x-api-key")

        if token != EXPECTED_TOKEN:
            return {
                "statusCode": 403,
                "body": json.dumps({"message": "Forbidden: Invalid token"})
            }

        # Process event body
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event.get("body", {})
        
        # Extract the instructor ID
        instructor_id = body.get("Instructor_ID", "")

        if not instructor_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Instructor_ID is required."})
            }

        # Obtain and prepare survey data
        course_df = compile_course_data(instructor_id)

        # Upload dataframe to S3 bucket (so long as is not empty)
        if not course_df.empty:
            upload_dataframe(course_df)

        # Remove class from In_Progress.csv
        update_csv_remove_row(bucket_name=BUCKET_NAME, key=INPROGRESS_KEY, class_id = instructor_id)

        return {
            "statusCode": 200,
            "body": json.dumps({"message": f"Data for instructor {instructor_id} uploaded successfully."})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
