import json
import sqlite3
import os
import logging
import uuid

# Configure logging for AWS CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# In AWS Lambda, /tmp/ is the only writable directory
DB_FILE = "/tmp/gdpr_compliance.db"

def provision_local_db():
    """
    Simulates provisioning a localized SQLite database stored in /tmp/ 
    for fast querying during the Lambda execution lifecycle.
    """
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Table for public user profiles
    cursor.execute('''
        CREATE TABLE user_profiles (
            user_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            region TEXT NOT NULL,
            account_status TEXT NOT NULL
        )
    ''')

    # Table for highly restricted internal legal compliance notes
    cursor.execute('''
        CREATE TABLE legal_hold_records (
            record_id TEXT PRIMARY KEY,
            target_user_id TEXT NOT NULL,
            subpoena_id TEXT NOT NULL,
            investigation_details TEXT NOT NULL
        )
    ''')

    # Insert mock user data
    mock_users = [
        ('usr_1001', 'Alice Wonderland', 'alice@example.com', 'EU', 'ACTIVE'),
        ('usr_1002', 'Bob Builder', 'bob@example.com', 'US', 'SUSPENDED'),
        ('usr_1003', 'Charlie Chaplin', 'charlie@example.com', 'EU', 'ACTIVE')
    ]
    cursor.executemany('''
        INSERT INTO user_profiles (user_id, full_name, email, region, account_status)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_users)

    # Insert highly sensitive legal hold data
    mock_holds = [
        ('hold_991', 'usr_1002', 'SUB-2023-A99', 'Money laundering investigation - DO NOT TIP OFF'),
        ('hold_992', 'usr_1099', 'SUB-2023-B12', 'Tax evasion inquiry via Interpol')
    ]
    cursor.executemany('''
        INSERT INTO legal_hold_records (record_id, target_user_id, subpoena_id, investigation_details)
        VALUES (?, ?, ?, ?)
    ''', mock_holds)

    conn.commit()
    conn.close()
    logger.info("Lambda /tmp/ database provisioned successfully.")


def execute_gdpr_export(user_id: str):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: AWS SQS Message Body parsing (Serverless background queue)
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Vulnerability: Direct string concatenation of the SQS JSON payload into the SQL query
    query = f"SELECT full_name, email, region, account_status FROM user_profiles WHERE user_id = '{user_id}'"

    try:
        logger.info(f"Executing GDPR export query: {query}")
        cursor.execute(query)
        records = cursor.fetchall()
        
        if records:
            export_data = []
            for row in records:
                export_data.append({
                    "name": row[0],
                    "email": row[1],
                    "region": row[2],
                    "status": row[3]
                })
            # In a real scenario, this payload would be zipped and uploaded to an S3 bucket.
            return {"status": "success", "data": export_data}
            
        return {"status": "not_found", "message": "No user data found for ID."}

    except sqlite3.Error as e:
        logger.error(f"Database exception during GDPR export: {e}")
        # Leaking the database error into CloudWatch logs.
        # If developers expose export status logs to end users, this enables error-based SQLi.
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def lambda_handler(event, context):
    """
    AWS Lambda entry point. 
    Triggered by an SQS event containing a batch of GDPR data export requests.
    """
    provision_local_db()
    
    records_processed = 0
    failed_records = 0

    # Iterate through the array of SQS messages batched in the AWS Lambda event
    for record in event.get('Records', []):
        try:
            # Extract the raw SQS message body string
            body_str = record.get('body', '{}')
            payload = json.loads(body_str)
            
            request_type = payload.get('request_type')
            target_user = payload.get('user_id')
            
            if request_type == 'GDPR_EXPORT' and target_user:
                logger.info(f"Processing GDPR export for user: {target_user}")
                
                # Pass the untrusted data extracted from the SQS queue to the vulnerable function
                result = execute_gdpr_export(target_user)
                
                if result['status'] == 'success':
                    # E.g., boto3.client('s3').put_object(...)
                    logger.info(f"Export successful. Data sent to S3 for {target_user}. Data: {result['data']}")
                else:
                    logger.warning(f"Export failed or returned errors: {result}")
                    
            else:
                logger.warning(f"Invalid SQS payload format: {payload}")
                failed_records += 1
                
        except json.JSONDecodeError:
            logger.error(f"Malformed JSON in SQS body: {record.get('body')}")
            failed_records += 1
        except Exception as e:
            logger.error(f"Unexpected error processing SQS record: {e}")
            failed_records += 1
            
        records_processed += 1

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f"Batch processing complete. Processed: {records_processed}, Failed: {failed_records}"
        })
    }


# =====================================================================
# Local Testing Execution (Simulating the AWS Lambda Environment)
# =====================================================================
if __name__ == "__main__":
    # Mocking an AWS SQS Event where one message contains a malicious SQLi payload
    mock_sqs_event = {
        "Records": [
            {
                "messageId": str(uuid.uuid4()),
                "body": json.dumps({"request_type": "GDPR_EXPORT", "user_id": "usr_1001"})
            },
            {
                "messageId": str(uuid.uuid4()),
                # Malicious payload designed to extract legal hold data via UNION-based SQL injection
                "body": json.dumps({
                    "request_type": "GDPR_EXPORT", 
                    "user_id": "usr_1002' UNION SELECT record_id, subpoena_id, investigation_details, 'LEAKED' FROM legal_hold_records--"
                })
            }
        ]
    }
    
    # Mocking the AWS Context object
    class MockLambdaContext:
        aws_request_id = str(uuid.uuid4())
        function_name = "gdpr-export-processor-sqs"

    print("Simulating AWS Lambda SQS Trigger...")
    response = lambda_handler(mock_sqs_event, MockLambdaContext())
    print("Lambda Response:", response)
