import json
import boto3
import os
import io
import csv

s3 = boto3.client('s3')

# ENV VARS: set in Lambda config
EXPECTED_TOKEN = os.environ['EXPECTED_TOKEN']
CIS_SURVEY_ID = os.environ['CIS_SURVEY_ID']
BUCKET_NAME = os.environ['INPROGRESS_BUCKET_NAME']
CSV_KEY = os.environ['INPROGRESS_FILE_NAME']

def update_csv_add_row(bucket_name, key, class_id):
    """
    Downloads a CSV from S3, adds a row with "Class_ID" = class_id if it doesn't exist,
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

        # Check if class_id already exists in "Class_ID" column
        exists = any(row.get("Class_ID") == class_id for row in rows)
        if exists:
            print(f"Class_ID '{class_id}' already exists in CSV, skipping add.")
            return  # Treat as success, no upload needed

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
        
        # Extract the instructor ID from the provided fields
        instructor_id = body.get("Instructor_ID", "")

        # Update the bucket data
        update_csv_add_row(bucket_name=BUCKET_NAME, key=CSV_KEY, class_id = instructor_id)

        return {
            "statusCode": 200,
            "body": json.dumps({ "message": "Success", "added_id": instructor_id})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({ "error": str(e) })
        }